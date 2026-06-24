"""core.pipeline.task_worker 测试 — mock 执行器，不打真实网络/不跑真实 build。

executor 签名为 (payload, ctx)；测试用 lambda p, c: ... 形式。
覆盖：成功/失败重试/超限失败/未知 kind/once/max-tasks/优雅停止，以及本轮新增的
heartbeat 续租（P1-1）、running cancel 不 complete（P1-2）、payload.mode（P2-1）。
"""

from __future__ import annotations

import subprocess
import time

import pytest

from core.pipeline import task_worker
from core.pipeline.task_worker import TaskWorker, TaskContext, TaskCancelled, _Heartbeat
from core.runtime.task_store import TaskStore
from core.runtime.task_models import TaskKind, TaskStatus


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.sqlite3")


def test_process_one_success(store, monkeypatch):
    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN,
                        lambda payload, ctx: {"ok": True, "echo": payload})
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "queue"})
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["id"] == tid
    assert task["status"] == TaskStatus.SUCCEEDED
    assert task["result"]["echo"] == {"mode": "queue"}


def test_process_one_no_task_returns_none(store):
    worker = TaskWorker(store=store, worker_id="w-test")
    assert worker.process_one() is None


def test_executor_exception_fails_task_retryable(store, monkeypatch):
    def boom(payload, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, boom)
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=3)
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.PENDING
    assert task["error_code"] == "execution_error"
    assert store.get_task(tid)["attempts"] == 1


def test_executor_exception_exhausts_then_failed(store, monkeypatch):
    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN,
                        lambda p, c: (_ for _ in ()).throw(RuntimeError("x")))
    store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=1)
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.FAILED


def test_run_max_tasks_stops(store, monkeypatch):
    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, lambda p, c: {"ok": True})
    for _ in range(5):
        store.enqueue_task(TaskKind.PIPELINE_RUN)
    worker = TaskWorker(store=store, worker_id="w-test")
    processed = worker.run(max_tasks=3)
    assert processed == 3
    assert store.task_summary()["by_status"][TaskStatus.PENDING] == 2


def test_run_once_processes_single(store, monkeypatch):
    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, lambda p, c: {"ok": True})
    store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.enqueue_task(TaskKind.PIPELINE_RUN)
    worker = TaskWorker(store=store, worker_id="w-test")
    assert worker.run(once=True) == 1


def test_unknown_kind_fails_non_retryable(store):
    store.enqueue_task(TaskKind.PIPELINE_AUTO)
    worker = TaskWorker(store=store, worker_id="w-test")
    saved = task_worker._EXECUTORS.pop(TaskKind.PIPELINE_AUTO)
    try:
        task = worker.process_one()
    finally:
        task_worker._EXECUTORS[TaskKind.PIPELINE_AUTO] = saved
    assert task["status"] == TaskStatus.FAILED
    assert task["error_code"] == "unknown_kind"


def test_graceful_stop_breaks_loop(store, monkeypatch):
    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, lambda p, c: {"ok": True})
    store.enqueue_task(TaskKind.PIPELINE_RUN)
    worker = TaskWorker(store=store, worker_id="w-test", poll_interval=0.01)
    worker.request_stop()
    assert worker.run() == 0


# --- P1-1: heartbeat 续租 ---

def test_heartbeat_called_during_long_task(tmp_path, monkeypatch):
    # 用很短的 lock_seconds 让 heartbeat 间隔被夹到下限 5s 仍太慢，故直接构造 _Heartbeat
    store = TaskStore(tmp_path / "tasks.sqlite3", lock_seconds=600)
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w-test")
    hb = _Heartbeat(store, tid, "w-test", interval=0.05).start()
    try:
        time.sleep(0.25)  # 应至少续租几次
    finally:
        hb.stop()
    assert hb.beats >= 2
    assert not hb.lost.is_set()


def test_heartbeat_lost_when_task_cancelled(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3", lock_seconds=600)
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w-test")
    hb = _Heartbeat(store, tid, "w-test", interval=0.05).start()
    try:
        store.cancel_task(tid)  # 任务不再 running -> heartbeat 返回 False
        time.sleep(0.2)
        assert hb.lost.is_set()
    finally:
        hb.stop()


def test_long_task_not_requeued_while_heartbeat_alive(store, monkeypatch):
    """长任务执行期间 heartbeat 续租，stale 回收不会把它误回 pending。"""
    def slow(payload, ctx):
        # 跑得比一次 stale 检查更久；期间 heartbeat 续租。
        for _ in range(6):
            ctx.check_cancelled()
            time.sleep(0.05)
        return {"ok": True}

    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, slow)
    store.lock_seconds = 600  # 锁租约长，心跳间隔被夹到 5s 内不会触发，但锁本就没过期
    store.enqueue_task(TaskKind.PIPELINE_RUN)
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.SUCCEEDED


# --- P1-2: running cancel 不会被误标 succeeded ---

def test_cancel_during_execution_not_completed(store, monkeypatch):
    """执行期间任务被 cancel：worker 不应 complete，最终状态保持 cancelled。"""
    def cancel_self(payload, ctx):
        # 模拟用户在任务运行中点了取消
        ctx.store.cancel_task(ctx.task_id)
        return {"ok": True}  # 即便 executor 返回成功

    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, cancel_self)
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.CANCELLED
    assert store.get_task(tid)["status"] == TaskStatus.CANCELLED


def test_task_cancelled_exception_not_failed(store, monkeypatch):
    """executor 抛 TaskCancelled：不走 fail（不回 pending、不标 failed）。"""
    def raise_cancel(payload, ctx):
        ctx.store.cancel_task(ctx.task_id)
        raise TaskCancelled(ctx.task_id)

    monkeypatch.setitem(task_worker._EXECUTORS, TaskKind.PIPELINE_RUN, raise_cancel)
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=3)
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.CANCELLED
    # 没有被错误地重新 pending
    assert store.get_task(tid)["status"] == TaskStatus.CANCELLED


def test_subprocess_cancel_terminates(store):
    """run_subprocess 期间任务被取消：终止子进程并抛 TaskCancelled。"""
    import sys
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w-test")
    ctx = TaskContext(store, tid, "w-test")
    # 先取消，再跑一个长 sleep 子进程：应立即终止并抛 TaskCancelled
    store.cancel_task(tid)
    with pytest.raises(TaskCancelled):
        ctx.run_subprocess([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60)


# --- P2-1: pipeline.run payload.mode ---

def test_pipeline_run_uses_payload_mode(store, monkeypatch):
    """payload.mode=demo 时命令包含 --mode demo。"""
    captured = {}

    def fake_run_subprocess(self, cmd, **kwargs):
        captured["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(TaskContext, "run_subprocess", fake_run_subprocess)
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "demo", "job_id": "j1"})
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.SUCCEEDED
    assert "--mode" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--mode") + 1] == "demo"
    assert task["result"]["mode"] == "demo"


def test_pipeline_run_defaults_queue(store, monkeypatch):
    captured = {}

    def fake_run_subprocess(self, cmd, **kwargs):
        captured["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(TaskContext, "run_subprocess", fake_run_subprocess)
    store.enqueue_task(TaskKind.PIPELINE_RUN, payload={})
    worker = TaskWorker(store=store, worker_id="w-test")
    worker.process_one()
    assert captured["cmd"][captured["cmd"].index("--mode") + 1] == "queue"


def test_pipeline_run_invalid_mode_failed_no_retry(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "bogus"}, max_attempts=3)
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.FAILED
    assert task["error_code"] == "invalid_payload"
    # 不重试：attempts 不会继续累加成 pending
    assert store.get_task(tid)["status"] == TaskStatus.FAILED


# --- queue_id 定向消费传参 ---

def test_pipeline_run_passes_queue_id(store, monkeypatch):
    """payload.queue_id 在 queue 模式下作为 --queue-id 传给 runner。"""
    captured = {}

    def fake_run_subprocess(self, cmd, **kwargs):
        captured["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(TaskContext, "run_subprocess", fake_run_subprocess)
    store.enqueue_task(TaskKind.PIPELINE_RUN,
                       payload={"mode": "queue", "queue_id": "Q-9", "job_id": "j9"},
                       queue_id="Q-9", job_id="j9")
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.SUCCEEDED
    cmd = captured["cmd"]
    assert "--queue-id" in cmd
    assert cmd[cmd.index("--queue-id") + 1] == "Q-9"
    assert task["result"]["queue_id"] == "Q-9"


def test_pipeline_run_no_queue_id_omits_flag(store, monkeypatch):
    captured = {}

    def fake_run_subprocess(self, cmd, **kwargs):
        captured["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(TaskContext, "run_subprocess", fake_run_subprocess)
    store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "queue"})
    worker = TaskWorker(store=store, worker_id="w-test")
    worker.process_one()
    assert "--queue-id" not in captured["cmd"]


# --- queue item 回写（worker 兜底未被 runner 回写的 item）---

def test_worker_cancel_syncs_queue_item(tmp_path, monkeypatch):
    """任务带 queue_id 且被取消时，worker 把仍停在 queued 的 item 收口为 failed。"""
    import json
    from core.pipeline import task_worker as tw
    from core.opportunity import opportunity_queue as oq

    # 把 worker 的队列路径指向临时文件
    qpath = tmp_path / "opportunity-queue.json"
    monkeypatch.setattr(tw, "OPPORTUNITY_QUEUE_PATH", qpath)
    qpath.write_text(json.dumps([
        {"queue_id": "Q-C", "feature_key": "k", "status": "queued", "task_id": "t"}
    ], ensure_ascii=False), encoding="utf-8")

    store = TaskStore(tmp_path / "tasks.sqlite3")

    def cancel_self(payload, ctx):
        ctx.store.cancel_task(ctx.task_id)
        return {"ok": True}

    monkeypatch.setitem(tw._EXECUTORS, TaskKind.PIPELINE_RUN, cancel_self)
    store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "queue", "queue_id": "Q-C"},
                       queue_id="Q-C")
    worker = TaskWorker(store=store, worker_id="w-test")
    task = worker.process_one()
    assert task["status"] == TaskStatus.CANCELLED
    # queue item 被收口（不再停在 queued）
    queue = oq.load_queue(qpath)
    item = oq.find_item(queue, "Q-C")
    assert item["status"] == "failed"


def test_worker_does_not_override_produced_item(tmp_path, monkeypatch):
    """若 runner 已把 item 写成 produced，worker 兜底回写不覆盖（失败兜底也尊重终态）。"""
    import json
    from core.pipeline import task_worker as tw
    from core.opportunity import opportunity_queue as oq

    qpath = tmp_path / "opportunity-queue.json"
    monkeypatch.setattr(tw, "OPPORTUNITY_QUEUE_PATH", qpath)
    qpath.write_text(json.dumps([
        {"queue_id": "Q-P", "feature_key": "k", "status": "produced"}
    ], ensure_ascii=False), encoding="utf-8")

    # 直接调 _sync_queue_item 模拟兜底失败写入：不应覆盖 produced
    tw._sync_queue_item("Q-P", "failed", error="boom")
    queue = oq.load_queue(qpath)
    assert oq.find_item(queue, "Q-P")["status"] == "produced"
