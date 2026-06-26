"""core.pipeline.task_worker — 任务队列消费 worker。

属于 pipeline 编排层。从 core.runtime.task_store 领取任务并按 kind 执行，复用现有
实现（不重写抓取/生成）：
- pipeline.run     → 子进程跑 core/pipeline/runner.py（mode 由 payload.mode 决定，
                     默认 queue；隔离 runner 模块级全局状态，与 auto_runner 同思路）。
- opportunity.crawl→ 调 core.opportunity.crawl_runner.run_once。
- pipeline.auto    → 调 core.pipeline.auto_runner.run_auto。

特性：claim / 后台 heartbeat 续租 / 执行期间感知 cancel（含子进程 terminate）/
complete / fail(可重试) / graceful stop / stale 回收。

CLI：
    python -m core.pipeline.task_worker --once
    python -m core.pipeline.task_worker --worker-id worker-local --once
    python -m core.pipeline.task_worker --worker-id worker-local --max-tasks 3
    python -m core.pipeline.task_worker --maintenance requeue-stale
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.runtime.task_store import TaskStore, get_default_store
from core.runtime.task_models import TaskKind
from core.runtime import task_models as tm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_RUNNER = PROJECT_ROOT / "core" / "pipeline" / "runner.py"
OPPORTUNITY_QUEUE_PATH = PROJECT_ROOT / "data" / "opportunity" / "opportunity-queue.json"

DEFAULT_POLL_INTERVAL = 2.0
# pipeline.run 子进程超时（秒）：含 npm install + build，给足时间但不无限挂。
PIPELINE_RUN_TIMEOUT = int(os.environ.get("TASK_PIPELINE_RUN_TIMEOUT", "1200"))

# runner.py 支持的 mode（pipeline.run payload.mode 白名单）。
PIPELINE_RUN_MODES = ("queue", "crawl", "auto", "demo", "real")
# heartbeat 间隔的下/上限（秒）：实际取 lock_seconds/3，再夹在该区间内。
HEARTBEAT_MIN_SECONDS = 5
HEARTBEAT_MAX_SECONDS = 60
# 子进程运行时轮询 cancel 的间隔（秒）。
SUBPROCESS_POLL_SECONDS = 1.0

# 维护（stale 回收）周期默认间隔（秒）。worker 主循环按此节流，多 worker 经维护锁互斥。
DEFAULT_MAINTENANCE_INTERVAL = 60
# 维护锁名（queue_maintenance.name）。
MAINTENANCE_STALE_RECOVERY = "stale_recovery"


class TaskCancelled(Exception):
    """任务在执行期间被取消（或锁被回收/丢失），executor 应尽快中止。"""


class InvalidPayload(Exception):
    """payload 非法（如不支持的 mode）。不可重试。"""


def _default_worker_id() -> str:
    """默认 worker id：主机名 + pid，便于排查是谁 claim 的。"""
    host = socket.gethostname() or "host"
    return f"{host}-{os.getpid()}"


def _heartbeat_interval(lock_seconds: int) -> float:
    """由锁租约推导 heartbeat 间隔：lock/3，夹在 [MIN, MAX]。"""
    return float(max(HEARTBEAT_MIN_SECONDS, min(HEARTBEAT_MAX_SECONDS, lock_seconds / 3)))


class _Heartbeat:
    """后台心跳线程：周期性 heartbeat_task 续租锁。

    heartbeat 返回 False（任务已不归本 worker：被取消/回收/完成）时，置位 lost 并停止；
    executor 通过 TaskContext 感知 lost 后应中止（含 terminate 子进程）。
    """

    def __init__(self, store: TaskStore, task_id: str, worker_id: str, interval: float):
        self.store = store
        self.task_id = task_id
        self.worker_id = worker_id
        self.interval = max(0.01, interval)
        self.lost = threading.Event()
        self.beats = 0  # 已成功续租次数（测试可断言 heartbeat 确实被调用）
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"hb-{task_id[:8]}", daemon=True)

    def _run(self) -> None:
        # 用 Event.wait 作为可中断的 sleep；返回 True 表示被 stop 唤醒。
        while not self._stop.wait(self.interval):
            try:
                ok = self.store.heartbeat_task(self.task_id, self.worker_id)
            except Exception:
                # DB 抖动不应让心跳线程崩溃；下一拍再试。
                continue
            if not ok:
                self.lost.set()
                return
            self.beats += 1

    def start(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)


class TaskContext:
    """传给 executor 的执行上下文：感知 cancel / 跑受监督的子进程。"""

    def __init__(self, store: TaskStore, task_id: str, worker_id: str,
                 heartbeat: _Heartbeat | None = None):
        self.store = store
        self.task_id = task_id
        self.worker_id = worker_id
        self._heartbeat = heartbeat

    @property
    def lock_lost(self) -> bool:
        return self._heartbeat is not None and self._heartbeat.lost.is_set()

    def is_cancelled(self) -> bool:
        """任务是否应中止：锁已丢失（含被取消），或 store 中状态已 cancelled。"""
        if self.lock_lost:
            return True
        return self.store.is_cancelled(self.task_id)

    def check_cancelled(self) -> None:
        if self.is_cancelled():
            raise TaskCancelled(self.task_id)

    def run_subprocess(self, cmd: list[str], *, env: dict | None = None,
                       cwd: str | None = None, timeout: int | None = None) -> tuple[int, str]:
        """跑子进程，期间周期性检查 cancel；cancel 则 terminate/kill 并抛 TaskCancelled。

        超过 timeout 抛 subprocess.TimeoutExpired（worker 转 retryable timeout）。
        返回 (returncode, 合并的 stdout/stderr 文本)。
        """
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd,
        )
        start = time.time()
        out = ""
        while True:
            try:
                # communicate 内部用线程排空管道，循环调用可继续读取，不会死锁。
                out, _ = proc.communicate(timeout=SUBPROCESS_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if self.is_cancelled():
                    self._terminate(proc)
                    raise TaskCancelled(self.task_id)
                if timeout is not None and (time.time() - start) > timeout:
                    self._terminate(proc)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                continue
        return proc.returncode, (out or "")

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """优雅 terminate，超时则 kill；吞掉清理期异常。"""
        try:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=5)
        except Exception:
            pass


# --- 各 kind 的执行器：executor(payload, ctx) → result dict ---
# 约定：失败抛异常（worker 统一 fail）；被取消抛 TaskCancelled；payload 非法抛 InvalidPayload。

def _run_pipeline_run(payload: dict, ctx: TaskContext) -> dict:
    """pipeline.run：子进程跑 runner.py --mode <payload.mode|queue>。

    用子进程隔离 runner 的模块级全局状态（与 auto_runner._generate_one 一致），
    这样同一 worker 连续跑多个生成任务不会串味。执行期间受 ctx 监督，可被 cancel 终止。

    payload 字段：mode（默认 queue）、job_id、queue_id（定向消费）、regions/platforms/
    limit/max_generate（crawl/auto 模式）。queue 模式下 runner 子进程自身会把对应 queue
    item 回写 produced/failed（见 runner._update_queue_after_run），worker 不重复写。
    """
    mode = (payload.get("mode") or "queue").strip()
    if mode not in PIPELINE_RUN_MODES:
        raise InvalidPayload(
            f"unsupported pipeline.run mode={mode!r}（合法：{PIPELINE_RUN_MODES}）"
        )
    ctx.check_cancelled()
    job_id = payload.get("job_id") or ("task-" + time.strftime("%Y%m%d-%H%M%S"))
    queue_id = payload.get("queue_id")
    cmd = [sys.executable, "-X", "utf8", str(PIPELINE_RUNNER), "--mode", mode, "--job-id", job_id]
    # 定向消费：queue 模式带 --queue-id，只消费指定 item（不串到别的 item）。
    if mode == "queue" and queue_id:
        cmd += ["--queue-id", str(queue_id)]
    # crawl/auto 模式透传抓取参数（与 runner.py CLI 对齐）。
    if mode in ("crawl", "auto"):
        if payload.get("regions"):
            cmd += ["--regions", _csv(payload["regions"])]
        if payload.get("platforms"):
            cmd += ["--platforms", _csv(payload["platforms"])]
        if payload.get("limit"):
            cmd += ["--limit", str(payload["limit"])]
    if mode == "auto":
        cmd += ["--max-generate", str(payload.get("max_generate", 1))]

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    returncode, out = ctx.run_subprocess(
        cmd, env=env, cwd=str(PROJECT_ROOT), timeout=PIPELINE_RUN_TIMEOUT,
    )
    result = {"job_id": job_id, "queue_id": queue_id, "mode": mode, "exit_code": returncode}
    # 读取 qa-report 摘要（与 auto_runner 一致），便于 result 可读。
    qa_path = PROJECT_ROOT / "data" / "outputs" / job_id / "qa-report.json"
    if qa_path.exists():
        try:
            import json
            qa = json.loads(qa_path.read_text(encoding="utf-8-sig"))
            result["qa_passed"] = qa.get("passed")
            result["build_passed"] = qa.get("checks", {}).get("build_passed", qa.get("build_passed"))
        except Exception:
            pass
    if returncode != 0:
        raise RuntimeError(f"pipeline.run exit={returncode}: {out[-800:]}")
    return result


def _csv(value) -> str:
    """list → 逗号分隔字符串；其它原样转 str。"""
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def _sync_queue_item(queue_id: str, target_status: str, *, job_id: str = "",
                     error: str | None = None) -> None:
    """把 queue item 同步到给定状态（best-effort，失败不影响任务终态）。

    与 runner 子进程的回写互补：queue 模式正常跑完时，runner 自身已把 item 写成
    produced/failed；本函数主要覆盖 runner 没机会回写的场景——任务被 cancel、或
    在起子进程前/payload 阶段就失败时，把仍停在 queued 的 item 收口，避免 queue item
    永远卡在 queued。只改匹配 queue_id 的那一个 item。
    """
    if not queue_id:
        return
    try:
        from core.opportunity import opportunity_queue as oq

        queue = oq.load_queue(OPPORTUNITY_QUEUE_PATH)
        item = oq.find_item(queue, queue_id)
        if item is None:
            return
        # runner 已写成终态（produced/failed）则不覆盖：尊重子进程的权威结果。
        if item.get("status") in (oq.STATUS_PRODUCED, oq.STATUS_FAILED):
            return
        oq.update_status(queue, queue_id, target_status, error=error, job_id=job_id or None)
        oq.save_queue(OPPORTUNITY_QUEUE_PATH, queue)
    except Exception:
        pass  # queue 回写是 best-effort，绝不让它打断任务状态机


def _run_opportunity_crawl(payload: dict, ctx: TaskContext) -> dict:
    """opportunity.crawl：调 crawl_runner.run_once（抓取写盘机会队列）。"""
    from core.opportunity import crawl_runner

    ctx.check_cancelled()  # 执行前检查
    # run_once 内部会归一化字符串/列表入参（_as_list），故 payload 原值（含字符串）可直接透传。
    rep = crawl_runner.run_once(
        regions=payload.get("regions"), platforms=payload.get("platforms"),
        categories=payload.get("categories"), entry_types=payload.get("entry_types"),
        limit=payload.get("limit"), dry_run=bool(payload.get("dry_run", False)),
        force_refresh=bool(payload.get("force_refresh", False)),
    )
    return {"counts": rep.get("counts", {}), "queue_stats": rep.get("queue_stats", {})}


def _run_pipeline_auto(payload: dict, ctx: TaskContext) -> dict:
    """pipeline.auto：调 auto_runner.run_auto（抓取 → 队列 → 生成）。"""
    from core.pipeline import auto_runner

    ctx.check_cancelled()  # 执行前检查
    rep = auto_runner.run_auto(
        job_id=payload.get("job_id"),
        regions=_csv(payload.get("regions") or ""),
        platforms=_csv(payload.get("platforms") or ""),
        limit=payload.get("limit"),
        max_generate=int(payload.get("max_generate", 1)),
        force_refresh=bool(payload.get("force_refresh", False)),
    )
    return {"auto_job_id": rep.get("auto_job_id"),
            "generated_jobs": rep.get("generated_jobs", [])}


_EXECUTORS = {
    TaskKind.PIPELINE_RUN: _run_pipeline_run,
    TaskKind.OPPORTUNITY_CRAWL: _run_opportunity_crawl,
    TaskKind.PIPELINE_AUTO: _run_pipeline_auto,
}


class TaskWorker:
    """单 worker 消费循环。一次只跑一个任务（串行），靠 claim 的写事务保证并发安全。

    执行期间开后台 heartbeat 线程续租锁（P1-1），并让 executor 通过 TaskContext 感知
    cancel（P1-2）：用户取消正在跑的任务时，子进程会被 terminate，任务不会被误标成功。
    """

    def __init__(
        self,
        store: TaskStore | None = None,
        worker_id: str | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        maintenance_interval: float = DEFAULT_MAINTENANCE_INTERVAL,
    ):
        self.store = store or get_default_store()
        self.worker_id = worker_id or _default_worker_id()
        self.poll_interval = poll_interval
        self.maintenance_interval = maintenance_interval
        self._stop = False
        # 告警：从 config 读阈值，复用 TelegramClient（缺 token/chat 时优雅降级）。
        from core.runtime import config as _cfg
        from core.runtime.alerting import AlertManager
        tg = None
        if _cfg.TELEGRAM_BOT_TOKEN and _cfg.ALERT_TELEGRAM_CHAT_ID:
            try:
                from core.platforms.telegram.api import TelegramClient
                tg = TelegramClient(_cfg.TELEGRAM_BOT_TOKEN)
            except Exception:
                tg = None
        self._expected_workers = _cfg.ALERT_EXPECTED_WORKERS
        self._worker_timeout = _cfg.ALERT_WORKER_TIMEOUT_SECONDS
        self._alert = AlertManager(
            self.store, telegram_client=tg, chat_id=_cfg.ALERT_TELEGRAM_CHAT_ID or None,
            log_path=PROJECT_ROOT / "data" / "runtime" / "logs" / "alerts.log",
            cooldown_seconds=_cfg.ALERT_COOLDOWN_SECONDS,
            recovery_confirmations=_cfg.ALERT_RECOVERY_CONFIRMATIONS,
        )
        self._last_failed_scan = tm.now_iso()

    def request_stop(self, *_args) -> None:
        """请求优雅停止：当前任务跑完后退出循环（不强杀正在跑的任务）。"""
        self._stop = True

    def _run_maintenance(self, force: bool = False) -> None:
        """周期维护：经维护锁抢占后回收 stale 锁。

        force=True 用于 worker 启动时立即跑一次（仍走维护锁，避免多 worker 同时启动重复跑）。
        整体 try/except：维护失败绝不拖垮消费循环。
        """
        try:
            # force（启动）时 interval=0：首个 worker 立即抢到；之后 interval 内不再重复。
            interval = 0 if force else self.maintenance_interval
            if not self.store.try_acquire_maintenance(
                MAINTENANCE_STALE_RECOVERY, int(interval), self.worker_id
            ):
                return
            stats = self.store.requeue_stale_tasks_detailed()
            if stats.get("requeued") or stats.get("failed"):
                print(f"[worker {self.worker_id}] maintenance: requeued "
                      f"{stats.get('requeued', 0)}, failed {stats.get('failed', 0)}",
                      flush=True)
            self._run_alert_checks()
        except Exception as e:  # noqa: BLE001 — 维护失败不影响消费
            print(f"[worker {self.worker_id}] maintenance error: {e}", flush=True)

    def _run_alert_checks(self) -> None:
        """worker 侧告警巡检：心跳 + 部分掉线 + 新失败任务 + 抓取零产出。

        整体 try/except：告警失败绝不拖垮维护。全挂检测由 API 看门狗负责（worker 全死自己报不了）。
        """
        try:
            self.store.worker_heartbeat(self.worker_id)
            # 部分掉线：0 < active < expected。active==0 留给 API 看门狗（这里 worker 自己活着，不会是 0）。
            active = self.store.count_active_workers(self._worker_timeout)
            if 0 < active < self._expected_workers:
                self._alert.fire("workers_partial_down",
                                 f"worker 在线 {active}/{self._expected_workers}")
            elif active >= self._expected_workers:
                self._alert.resolve("workers_partial_down")
            # 新失败任务：finished_at 晚于上次扫描的 failed。
            scan_from = self._last_failed_scan
            self._last_failed_scan = tm.now_iso()
            for t in self.store.list_tasks(status="failed", limit=50):
                fin = t.get("finished_at") or ""
                if fin > scan_from:
                    self._alert.fire(f"task_failed:{t['id']}",
                                     f"任务失败 kind={t.get('kind')} code={t.get('error_code')}")
            # 抓取零产出：读 crawl-report.json 的 counts.queue_pending（纯读数据文件，不 import 抓取代码）。
            self._check_crawl_zero_output()
        except Exception as e:  # noqa: BLE001
            print(f"[worker {self.worker_id}] alert check error: {e}", flush=True)

    def _check_crawl_zero_output(self) -> None:
        """读最近 crawl-report，queue_pending==0 则告警（按日期 key 去重）。"""
        import json
        report_path = PROJECT_ROOT / "data" / "opportunity" / "crawl-report.json"
        if not report_path.exists():
            return
        try:
            rep = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        counts = rep.get("counts") or {}
        date = rep.get("date") or "unknown"
        if counts.get("queue_pending", -1) == 0:
            self._alert.fire(f"crawl_zero_output:{date}", f"抓取 {date} 零产出（queue_pending=0）")

    def process_one(self) -> dict | None:
        """claim 并执行一个任务。返回执行后的任务 dict；无可领取任务返回 None。"""
        task = self.store.claim_next_task(self.worker_id)
        if task is None:
            return None
        task_id = task["id"]
        kind = task["kind"]
        queue_id = task.get("queue_id") or (task.get("payload") or {}).get("queue_id") or ""
        job_id = task.get("job_id") or (task.get("payload") or {}).get("job_id") or ""
        executor = _EXECUTORS.get(kind)
        if executor is None:
            # 未知 kind：不可重试地失败，避免无限占用队列。
            return self.store.fail_task(
                task_id, error_code="unknown_kind",
                error_message=f"no executor for kind={kind}", retryable=False,
            )

        # 后台心跳续租 + 执行上下文（感知 cancel / 监督子进程）。
        hb = _Heartbeat(
            self.store, task_id, self.worker_id,
            interval=_heartbeat_interval(self.store.lock_seconds),
        ).start()
        ctx = TaskContext(self.store, task_id, self.worker_id, heartbeat=hb)
        try:
            result = executor(task.get("payload") or {}, ctx)
        except TaskCancelled:
            # 用户取消（或锁丢失/被回收）：不要 complete，也不要把它重新 pending。
            self._sync_queue_terminal(queue_id, "failed", job_id=job_id, error="cancelled")
            return self._handle_cancel(task_id)
        except InvalidPayload as e:
            self._sync_queue_terminal(queue_id, "failed", job_id=job_id, error=str(e))
            return self.store.fail_task(
                task_id, error_code="invalid_payload",
                error_message=str(e), retryable=False,
            )
        except subprocess.TimeoutExpired:
            return self.store.fail_task(
                task_id, error_code="timeout",
                error_message="task execution timed out", retryable=True,
            )
        except Exception as e:  # noqa: BLE001 — 统一兜底，转成 fail（带脱敏）
            # 执行中途若已被取消，按取消处理，不要污染成 failed。
            if self.store.is_cancelled(task_id):
                self._sync_queue_terminal(queue_id, "failed", job_id=job_id, error="cancelled")
                return self._handle_cancel(task_id)
            # runner 子进程在 queue 模式已自行回写 produced/failed；这里只兜底未回写的 item。
            self._sync_queue_terminal(queue_id, "failed", job_id=job_id, error=str(e))
            return self.store.fail_task(
                task_id, error_code="execution_error",
                error_message=f"{type(e).__name__}: {e}", retryable=True,
            )
        finally:
            hb.stop()

        # 执行成功返回后再确认一次：期间被取消 / 锁丢失 → 不 complete。
        if ctx.is_cancelled():
            self._sync_queue_terminal(queue_id, "failed", job_id=job_id, error="cancelled")
            return self._handle_cancel(task_id)
        return self.store.complete_task(task_id, result=result)

    @staticmethod
    def _sync_queue_terminal(queue_id: str, status: str, *, job_id: str = "",
                             error: str | None = None) -> None:
        """终态时同步 queue item（best-effort；runner 已写终态则不覆盖）。"""
        _sync_queue_item(queue_id, status, job_id=job_id, error=error)

    def _handle_cancel(self, task_id: str) -> dict | None:
        """把被取消的任务落定为 cancelled（若 store 中尚未取消，如锁丢失场景）。"""
        current = self.store.get_status(task_id)
        if current == "cancelled":
            return self.store.get_task(task_id)
        # 锁丢失但未取消（如被 stale 回收）：不强标 cancelled，保留 store 现状返回。
        return self.store.get_task(task_id)

    def run(self, once: bool = False, max_tasks: int | None = None) -> int:
        """worker 主循环。

        - 启动时先跑一次 stale 回收（经维护锁，多 worker 不重复）。
        - 主循环每 maintenance_interval 秒经维护锁尝试一次回收。
        - once=True：跑一次启动回收 + 尝试领取一个任务就返回（无任务也返回，不阻塞）。
        - max_tasks=N：最多处理 N 个任务后停止。
        - 否则持续轮询，直到收到 stop（SIGINT/SIGTERM）。
        返回已处理（claim 成功）的任务数。
        """
        self._run_maintenance(force=True)  # 启动即回收 stale（被维护锁限流）
        last_maintenance = time.monotonic()
        processed = 0
        while not self._stop:
            # 周期维护：到点经维护锁尝试回收。
            if time.monotonic() - last_maintenance >= self.maintenance_interval:
                self._run_maintenance(force=False)
                last_maintenance = time.monotonic()
            task = self.process_one()
            if task is not None:
                processed += 1
                status = task.get("status")
                tid = task.get("id", "")[:12]
                print(f"[worker {self.worker_id}] task {tid} kind={task.get('kind')} -> {status}",
                      flush=True)
                if once:
                    break
                if max_tasks is not None and processed >= max_tasks:
                    break
                continue
            # 无可领取任务
            if once or max_tasks is not None:
                break
            time.sleep(self.poll_interval)
        return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="任务队列 worker：消费 task_store 中的任务")
    parser.add_argument("--db", default=None, help="任务库路径（默认 data/runtime/tasks.sqlite3）")
    parser.add_argument("--worker-id", default=None, help="worker 标识（默认 host-pid）")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL,
                        help="轮询空队列的间隔秒数")
    parser.add_argument("--once", action="store_true", help="只领取并处理一个任务后退出")
    parser.add_argument("--max-tasks", type=int, default=None, help="最多处理 N 个任务后退出")
    parser.add_argument("--maintenance", choices=["requeue-stale"], default=None,
                        help="维护动作：requeue-stale 回收锁过期的 running 任务")
    args = parser.parse_args()

    store = TaskStore(args.db) if args.db else get_default_store()

    if args.maintenance == "requeue-stale":
        stats = store.requeue_stale_tasks_detailed()
        print(f"[worker] requeued {stats['requeued']} stale task(s), "
              f"failed {stats['failed']} exhausted task(s)")
        return

    worker = TaskWorker(store=store, worker_id=args.worker_id, poll_interval=args.poll_interval)
    # 优雅停止：收到信号后跑完当前任务退出。
    try:
        signal.signal(signal.SIGINT, worker.request_stop)
        signal.signal(signal.SIGTERM, worker.request_stop)
    except (ValueError, OSError):
        pass  # 非主线程或不支持信号的平台：忽略
    n = worker.run(once=args.once, max_tasks=args.max_tasks)
    print(f"[worker {worker.worker_id}] processed {n} task(s)")


if __name__ == "__main__":
    main()
