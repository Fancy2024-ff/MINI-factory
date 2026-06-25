# 任务队列稳定可运维化改造 — A 阶段实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把任务队列从「能跑」升级到「稳定可运维」——常驻 worker、自动 stale 回收、多 worker 并发、最小健康指标，不重构调度算法。

**架构：** 增量增强现有 SQLite+WAL 队列。新增单行 `queue_maintenance` 表做多 worker 维护抢占锁；worker 主循环按 interval 自动回收 stale 锁；新增 `/api/tasks/health` 健康指标接口；deploy/ 配置层提供 launchd/systemd 常驻，平台差异不进业务代码。

**技术栈：** Python 标准库 sqlite3、pytest、FastAPI、Vue 3 + vitest、launchd（plist）、systemd（template unit）。

**规格来源：** `docs/superpowers/specs/2026-06-25-task-queue-hardening-design.md`

---

## 文件结构

| 文件 | 职责 | 任务 |
|------|------|------|
| `core/runtime/task_store.py` | 新增 `queue_maintenance` 表 + `try_acquire_maintenance()` + `health_summary()` | A1, A4 |
| `core/runtime/tests/test_task_store.py` | 维护锁、并发 claim、健康指标测试 | A1, A3, A4 |
| `core/pipeline/task_worker.py` | `run()` 内启动时 + 周期 stale 回收，`maintenance_interval` | A2 |
| `core/pipeline/tests/test_task_worker.py` | 启动回收、周期回收测试 | A2 |
| `apps/api/main.py` | `GET /api/tasks/health` | A4 |
| `apps/api/tests/test_task_endpoints.py` | health 接口测试 | A4 |
| `apps/web/src/types/job.ts` | `TaskHealth` 类型 | A4 |
| `apps/web/src/services/api.ts` | `getTaskHealth()` | A4 |
| `apps/web/src/components/TaskQueuePanel.vue` | “队列健康”一行展示 | A4 |
| `apps/web/src/App.vue` | 加载并传入 health | A4 |
| `apps/web/src/__tests__/taskQueueViews.test.ts` | 健康行展示测试 | A4 |
| `deploy/launchd/com.minifactory.worker.plist` | Mac 常驻配置 | A5 |
| `deploy/systemd/minifactory-worker@.service` | Linux 模板单元 | A5 |
| `deploy/README.md` | 安装/启动/多 worker/日志说明 | A5 |
| `docs/operation/RUNBOOK.md` | 补多 worker 运维说明 | A3, A5 |

---

## 任务 A1：维护锁机制（queue_maintenance 表 + CAS 抢占）

先做：A2 的周期回收依赖它防多 worker 重复维护。

**文件：**
- 修改：`core/runtime/task_store.py`（`_SCHEMA` 加表、`init_schema` 幂等、新增 `try_acquire_maintenance`）
- 测试：`core/runtime/tests/test_task_store.py`

- [ ] **步骤 1：编写失败的测试**

在 `core/runtime/tests/test_task_store.py` 末尾追加：

```python
def test_maintenance_lock_first_acquire_succeeds(store):
    now = now_iso()
    assert store.try_acquire_maintenance("stale_recovery", 60, "w1", now=now) is True


def test_maintenance_lock_within_interval_blocked(store):
    now = now_iso()
    assert store.try_acquire_maintenance("stale_recovery", 60, "w1", now=now) is True
    # 同一时刻再抢：interval 未到，拒绝
    assert store.try_acquire_maintenance("stale_recovery", 60, "w2", now=now) is False


def test_maintenance_lock_after_interval_reacquire(store):
    from core.runtime.task_store import _add_seconds
    now = now_iso()
    assert store.try_acquire_maintenance("stale_recovery", 60, "w1", now=now) is True
    later = _add_seconds(now, 61)  # 超过 interval
    assert store.try_acquire_maintenance("stale_recovery", 60, "w2", now=later) is True


def test_maintenance_lock_concurrent_single_winner(store):
    import threading
    now = now_iso()
    results = []
    lock = threading.Lock()

    def worker(wid):
        ok = store.try_acquire_maintenance("stale_recovery", 60, wid, now=now)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 并发 8 个 worker 同一时刻抢，恰好一个成功
    assert results.count(True) == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest core/runtime/tests/test_task_store.py -k maintenance_lock -v`
预期：FAIL，`AttributeError: 'TaskStore' object has no attribute 'try_acquire_maintenance'`

- [ ] **步骤 3：实现 — 建表 + 方法**

在 `core/runtime/task_store.py` 的 `_SCHEMA` 字符串内（`CREATE INDEX ... idx_tasks_created_at` 之后、闭合 `"""` 之前）追加建表语句：

```sql
CREATE TABLE IF NOT EXISTS queue_maintenance (
    name        TEXT PRIMARY KEY,
    last_run_at TEXT,
    runner      TEXT
);
```

在 `claim_next_task` 方法之前（约第 228 行），新增方法：

```python
    def try_acquire_maintenance(
        self, name: str, interval_seconds: int, worker_id: str, now: str | None = None
    ) -> bool:
        """多 worker 维护抢占锁：距上次运行已超过 interval 才允许执行，返回是否抢到。

        用一次 BEGIN IMMEDIATE 写事务做 CAS：先 UPSERT 占位行（首次），再带
        last_run_at 条件 UPDATE。rowcount>0 表示本 worker 抢到了这一轮维护权。
        复用现有串行化保证，多 worker 同一时刻只有一个返回 True。
        """
        now = now or tm.now_iso()
        threshold = _add_seconds(now, -interval_seconds)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 首次：插入占位行（last_run_at=NULL，表示从未跑过）。
            conn.execute(
                "INSERT OR IGNORE INTO queue_maintenance (name, last_run_at, runner) "
                "VALUES (?, NULL, NULL)",
                (name,),
            )
            cur = conn.execute(
                """
                UPDATE queue_maintenance
                SET last_run_at = ?, runner = ?
                WHERE name = ? AND (last_run_at IS NULL OR last_run_at <= ?)
                """,
                (now, worker_id, name, threshold),
            )
            conn.execute("COMMIT")
            return cur.rowcount > 0
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest core/runtime/tests/test_task_store.py -k maintenance_lock -v`
预期：4 PASS。
再跑全量回归：`python -m pytest core/runtime/tests/test_task_store.py -q` 预期全绿。

- [ ] **步骤 5：Commit**

```bash
git add core/runtime/task_store.py core/runtime/tests/test_task_store.py
git commit -m "feat(task-store): 多 worker 维护抢占锁 queue_maintenance(A1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A2：worker 内 stale 自动回收

**文件：**
- 修改：`core/pipeline/task_worker.py`（`TaskWorker.__init__` 加 `maintenance_interval`；新增 `_run_maintenance`；`run()` 启动时跑一次 + 主循环周期跑）
- 测试：`core/pipeline/tests/test_task_worker.py`

- [ ] **步骤 1：编写失败的测试**

在 `core/pipeline/tests/test_task_worker.py` 末尾追加：

```python
def test_stale_recovery_runs_on_startup(store, monkeypatch):
    """worker.run() 启动时先跑一次 stale 回收（即使无任务可领）。"""
    calls = {"n": 0}
    monkeypatch.setattr(store, "requeue_stale_tasks_detailed",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {"requeued": 0, "failed": 0})
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    worker.run(once=True)  # once：领不到任务也会先跑启动回收
    assert calls["n"] >= 1


def test_maintenance_skipped_when_lock_not_acquired(store, monkeypatch):
    """维护锁未抢到时不调用 requeue（多 worker 防重复）。"""
    monkeypatch.setattr(store, "try_acquire_maintenance", lambda *a, **k: False)
    called = {"n": 0}
    monkeypatch.setattr(store, "requeue_stale_tasks_detailed",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {"requeued": 0, "failed": 0})
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    worker._run_maintenance(force=False)
    assert called["n"] == 0


def test_maintenance_runs_when_lock_acquired(store, monkeypatch):
    monkeypatch.setattr(store, "try_acquire_maintenance", lambda *a, **k: True)
    called = {"n": 0}
    monkeypatch.setattr(store, "requeue_stale_tasks_detailed",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {"requeued": 1, "failed": 0})
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    worker._run_maintenance(force=False)
    assert called["n"] == 1


def test_maintenance_exception_does_not_break_worker(store, monkeypatch):
    """维护逻辑抛异常不应让 worker 崩溃。"""
    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(store, "try_acquire_maintenance", boom)
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    worker._run_maintenance(force=False)  # 不抛
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest core/pipeline/tests/test_task_worker.py -k "maintenance or stale_recovery" -v`
预期：FAIL，`TypeError: __init__() got an unexpected keyword argument 'maintenance_interval'`

- [ ] **步骤 3：实现**

在 `core/pipeline/task_worker.py` 顶部常量区（`SUBPROCESS_POLL_SECONDS = 1.0` 之后）加：

```python
# 维护（stale 回收）周期默认间隔（秒）。worker 主循环按此节流，多 worker 经维护锁互斥。
DEFAULT_MAINTENANCE_INTERVAL = 60
# 维护锁名（queue_maintenance.name）。
MAINTENANCE_STALE_RECOVERY = "stale_recovery"
```

修改 `TaskWorker.__init__`（约第 310-319 行），加 `maintenance_interval` 参数与 `_started` 标志：

```python
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
        self._maintenance_started = False
```

在 `request_stop` 方法之后、`process_one` 之前，新增 `_run_maintenance`：

```python
    def _run_maintenance(self, force: bool = False) -> None:
        """周期维护：经维护锁抢占后回收 stale 锁。

        force=True 用于 worker 启动时立即跑一次（仍走维护锁，避免多 worker 同时启动重复跑）。
        整体 try/except：维护失败绝不拖垮消费循环。
        """
        try:
            # interval=0 时（force 启动）也要让首个 worker 能抢到：用一个极小阈值即可，
            # 这里统一走 try_acquire_maintenance(interval) 语义——启动后 interval 内不会再跑。
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
        except Exception as e:  # noqa: BLE001 — 维护失败不影响消费
            print(f"[worker {self.worker_id}] maintenance error: {e}", flush=True)
```

修改 `run()` 方法（约第 399-425 行），在循环开始前跑启动回收、循环内按 interval 周期跑。替换整个 `run` 方法体内的循环逻辑：

```python
    def run(self, once: bool = False, max_tasks: int | None = None) -> int:
        """worker 主循环。

        - 启动时先跑一次 stale 回收（经维护锁，多 worker 不重复）。
        - 主循环每 maintenance_interval 秒经维护锁尝试一次回收。
        - once=True：跑一次启动回收 + 尝试领一个任务就返回。
        - max_tasks=N：最多处理 N 个任务后停止。
        - 否则持续轮询，直到收到 stop（SIGINT/SIGTERM）。
        返回已处理（claim 成功）的任务数。
        """
        import time as _time
        self._run_maintenance(force=True)  # 启动即回收 stale（被维护锁限流）
        last_maintenance = _time.monotonic()
        processed = 0
        while not self._stop:
            # 周期维护：到点经维护锁尝试回收。
            if _time.monotonic() - last_maintenance >= self.maintenance_interval:
                self._run_maintenance(force=False)
                last_maintenance = _time.monotonic()
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
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest core/pipeline/tests/test_task_worker.py -v`
预期：新增 4 个 PASS，且现有 `test_long_task_not_requeued_while_heartbeat_alive` 等保持绿。

- [ ] **步骤 5：Commit**

```bash
git add core/pipeline/task_worker.py core/pipeline/tests/test_task_worker.py
git commit -m "feat(task-worker): worker 内启动时+周期 stale 自动回收(A2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A3：多 worker 并发安全验证（不改 claim 核心）

`claim_next_task` 已用 `BEGIN IMMEDIATE` 保证并发安全；本任务只补强回归测试 + 去重断言，不改核心逻辑。

**文件：**
- 测试：`core/runtime/tests/test_task_store.py`
- 修改：`docs/operation/RUNBOOK.md`（补多 worker 说明）

- [ ] **步骤 1：编写失败/未覆盖的测试**

在 `core/runtime/tests/test_task_store.py` 末尾追加：

```python
def test_concurrent_claim_no_duplicate(tmp_path):
    """多线程并发 claim：每个 task 恰好被一个 worker 领到，无重复。"""
    import threading
    store = TaskStore(tmp_path / "tasks.sqlite3", lock_seconds=600)
    n_tasks = 20
    for _ in range(n_tasks):
        store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "queue"})

    claimed: list[str] = []
    lock = threading.Lock()

    def grab():
        while True:
            t = store.claim_next_task(f"w-{threading.get_ident()}")
            if t is None:
                return
            with lock:
                claimed.append(t["id"])

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 每个任务恰好被领一次：无重复、无遗漏
    assert len(claimed) == n_tasks
    assert len(set(claimed)) == n_tasks


def test_find_active_by_queue_id_dedupes(store):
    """同 queue_id 已有 active(pending) task 时，find_active_by_queue_id 命中，用于去重。"""
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "queue"},
                             queue_id="q-dup-1")
    active = store.find_active_by_queue_id("q-dup-1")
    assert active is not None and active["id"] == tid
    # 领取后变 running 仍算 active
    store.claim_next_task("w1")
    assert store.find_active_by_queue_id("q-dup-1")["id"] == tid
    # 完成后不再 active
    store.complete_task(tid, result={})
    assert store.find_active_by_queue_id("q-dup-1") is None
```

- [ ] **步骤 2：运行测试验证**

运行：`python -m pytest core/runtime/tests/test_task_store.py -k "concurrent_claim or find_active_by_queue_id_dedupes" -v`
预期：2 PASS（验证现有实现已并发安全 + 去重正确；若失败说明并发有缺陷，需停下排查而非改测试）。

- [ ] **步骤 3：补 RUNBOOK 多 worker 说明**

在 `docs/operation/RUNBOOK.md` 的 worker 启动段落（含 `python -m core.pipeline.task_worker --worker-id worker-local` 那段）后追加：

```markdown
### 多 worker 并发（建议 2，可配置到 4）

SQLite + WAL 下，`claim_next_task` 用 `BEGIN IMMEDIATE` 写事务串行化，多个 worker
不会领到同一个任务。pipeline 任务大头是 npm build（CPU/IO），claim 写事务仅毫秒级，
因此 2~4 个 worker 几乎不撞写锁，吞吐近线性提升。再多收益递减，不建议超过 4。

每个 worker 用不同 worker-id（默认 host-pid 已天然区分）：

    python -m core.pipeline.task_worker --worker-id worker-1
    python -m core.pipeline.task_worker --worker-id worker-2

stale 回收由 worker 内部维护锁互斥，多 worker 不会重复回收（见 queue_maintenance 表）。
```

- [ ] **步骤 4：运行全量回归确认无回归**

运行：`python -m pytest core/runtime/tests/test_task_store.py -q`
预期：全绿。

- [ ] **步骤 5：Commit**

```bash
git add core/runtime/tests/test_task_store.py docs/operation/RUNBOOK.md
git commit -m "test(task-store): 多 worker 并发 claim 不重复 + queue_id 去重回归(A3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A4a：健康指标 — 存储层 `health_summary()`

**文件：**
- 修改：`core/runtime/task_store.py`（新增 `health_summary()`）
- 测试：`core/runtime/tests/test_task_store.py`

- [ ] **步骤 1：编写失败的测试**

在 `core/runtime/tests/test_task_store.py` 末尾追加：

```python
def test_health_summary_empty(store):
    h = store.health_summary()
    for key in ("total", "pending", "running", "succeeded", "failed", "cancelled",
                "oldest_pending_seconds", "running_count", "active_worker_count"):
        assert key in h
    assert h["total"] == 0
    assert h["pending"] == 0
    assert h["oldest_pending_seconds"] == 0
    assert h["active_worker_count"] == 0


def test_health_summary_counts_and_running(store):
    store.enqueue_task(TaskKind.PIPELINE_RUN)          # pending
    running_id = store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w1")                         # 领最早那个？按 created 顺序
    h = store.health_summary()
    assert h["total"] == 2
    assert h["running"] == 1
    assert h["pending"] == 1
    assert h["running_count"] == 1
    # 有一个 fresh 锁的 worker：active_worker_count 计入
    assert h["active_worker_count"] == 1


def test_health_summary_oldest_pending_positive(store):
    from core.runtime.task_store import _add_seconds
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    # 把 created_at 改早 120 秒，模拟等待
    conn = store._conn()
    try:
        old = _add_seconds(now_iso(), -120)
        conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (old, tid))
    finally:
        store._close(conn)
    h = store.health_summary()
    assert h["oldest_pending_seconds"] >= 110  # 约 120，留宽容
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest core/runtime/tests/test_task_store.py -k health_summary -v`
预期：FAIL，`AttributeError: 'TaskStore' object has no attribute 'health_summary'`

- [ ] **步骤 3：实现**

在 `core/runtime/task_store.py` 的 `task_summary` 方法之后（约第 595 行）新增：

```python
    def health_summary(self) -> dict:
        """队列健康指标（供 /api/tasks/health 与 dashboard）。

        返回：各状态计数 + total；oldest_pending_seconds（最老 pending 等待秒数）；
        running_count；active_worker_count（近似：locked_until 未过期的不同 locked_by 数，
        即仍在 heartbeat 续租的活跃 worker）。
        """
        now = tm.now_iso()
        conn = self._conn()
        try:
            by_status = {s: 0 for s in TaskStatus.ALL}
            for r in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"):
                by_status[r["status"]] = r["n"]
            total = sum(by_status.values())
            # 最老 pending 等待秒数：取 min(created_at) 的 pending。
            oldest_row = conn.execute(
                "SELECT MIN(created_at) AS oldest FROM tasks WHERE status = ?",
                (TaskStatus.PENDING,),
            ).fetchone()
            oldest_pending_seconds = 0
            if oldest_row and oldest_row["oldest"]:
                from datetime import datetime
                delta = datetime.fromisoformat(now) - datetime.fromisoformat(oldest_row["oldest"])
                oldest_pending_seconds = max(0, int(delta.total_seconds()))
            # 活跃 worker 近似：running 且锁未过期的不同 locked_by 数。
            worker_row = conn.execute(
                """
                SELECT COUNT(DISTINCT locked_by) AS n FROM tasks
                WHERE status = ? AND locked_by IS NOT NULL
                  AND locked_until IS NOT NULL AND locked_until > ?
                """,
                (TaskStatus.RUNNING, now),
            ).fetchone()
            active_worker_count = worker_row["n"] if worker_row else 0
            return {
                "total": total,
                "pending": by_status[TaskStatus.PENDING],
                "running": by_status[TaskStatus.RUNNING],
                "succeeded": by_status[TaskStatus.SUCCEEDED],
                "failed": by_status[TaskStatus.FAILED],
                "cancelled": by_status[TaskStatus.CANCELLED],
                "oldest_pending_seconds": oldest_pending_seconds,
                "running_count": by_status[TaskStatus.RUNNING],
                "active_worker_count": active_worker_count,
            }
        finally:
            self._close(conn)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest core/runtime/tests/test_task_store.py -k health_summary -v`
预期：3 PASS。

- [ ] **步骤 5：Commit**

```bash
git add core/runtime/task_store.py core/runtime/tests/test_task_store.py
git commit -m "feat(task-store): health_summary 健康指标聚合(A4a)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A4b：健康指标 — API 接口 `GET /api/tasks/health`

**文件：**
- 修改：`apps/api/main.py`（新增接口，紧邻 `tasks_summary`，约第 842-845 行后）
- 测试：`apps/api/tests/test_task_endpoints.py`

- [ ] **步骤 1：编写失败的测试**

在 `apps/api/tests/test_task_endpoints.py` 末尾追加：

```python
def test_tasks_health_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/tasks/health").status_code == 401


def test_tasks_health_shape(server_client, auth_headers):
    client, _ = server_client
    _enqueue(client, auth_headers, payload={"mode": "queue"})
    res = client.get("/api/tasks/health", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    for key in ("total", "pending", "running", "succeeded", "failed", "cancelled",
                "oldest_pending_seconds", "running_count", "active_worker_count"):
        assert key in body
    assert body["total"] == 1
    assert body["pending"] == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest apps/api/tests/test_task_endpoints.py -k health -v`
预期：`test_tasks_health_shape` FAIL（404 Not Found）。

- [ ] **步骤 3：实现**

在 `apps/api/main.py` 的 `tasks_summary` 函数之后（约第 846 行）新增：

```python
@app.get("/api/tasks/health", dependencies=[Depends(verify_api_key)])
def tasks_health():
    """队列健康指标：状态计数 + 最老 pending 等待 + 活跃 worker 近似数。"""
    return _task_store().health_summary()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest apps/api/tests/test_task_endpoints.py -k health -v`
预期：2 PASS。

- [ ] **步骤 5：Commit**

```bash
git add apps/api/main.py apps/api/tests/test_task_endpoints.py
git commit -m "feat(api): GET /api/tasks/health 健康指标接口(A4b)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A4c：健康指标 — 前端“队列健康”一行

**文件：**
- 修改：`apps/web/src/types/job.ts`（加 `TaskHealth`）
- 修改：`apps/web/src/services/api.ts`（加 `getTaskHealth`）
- 修改：`apps/web/src/components/TaskQueuePanel.vue`（加 health prop + 一行展示）
- 修改：`apps/web/src/App.vue`（加载 health 并传入）
- 测试：`apps/web/src/__tests__/taskQueueViews.test.ts`

- [ ] **步骤 1：编写失败的测试**

在 `apps/web/src/__tests__/taskQueueViews.test.ts` 内 `describe('TaskQueuePanel', ...)` 中追加一个用例（沿用文件顶部 `summary()`/`tasks()` 辅助；新增 `health()` 辅助放在 `tasks()` 之后）：

```typescript
function health() {
  return {
    total: 4, pending: 1, running: 1, succeeded: 1, failed: 1, cancelled: 0,
    oldest_pending_seconds: 125, running_count: 1, active_worker_count: 2,
  }
}
```

```typescript
  it('renders queue health line when health provided', () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '', health: health() },
    })
    const line = wrapper.find('[data-testid="queue-health"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('2')      // active_worker_count
    expect(line.text()).toContain('125')    // oldest_pending_seconds
  })
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd apps/web && npx vitest run src/__tests__/taskQueueViews.test.ts`
预期：新用例 FAIL（找不到 `[data-testid="queue-health"]`）。

- [ ] **步骤 3a：加类型**

在 `apps/web/src/types/job.ts` 的 `TaskSummary` 接口之后（约第 112 行）新增：

```typescript
export interface TaskHealth {
  total: number
  pending: number
  running: number
  succeeded: number
  failed: number
  cancelled: number
  oldest_pending_seconds: number
  running_count: number
  active_worker_count: number
}
```

- [ ] **步骤 3b：加 API 方法**

在 `apps/web/src/services/api.ts` 的 `getTaskSummary` 行（约第 91 行）之后新增。先确保文件顶部 import 含 `TaskHealth`（与 `TaskSummary` 同一 import 行追加）：

```typescript
  getTaskHealth: () => get<TaskHealth>('/api/tasks/health'),
```

- [ ] **步骤 3c：面板加展示**

在 `apps/web/src/components/TaskQueuePanel.vue` 的 `defineProps`（约第 5-9 行）加 `health`：

```typescript
const props = defineProps<{
  summary: TaskSummary | null
  tasks: TaskItem[]
  busyTaskId: string
  health?: TaskHealth | null
}>()
```

文件顶部 import 改为：

```typescript
import type { TaskItem, TaskSummary, TaskHealth } from '../types/job'
```

在 `<template>` 内状态 tiles 区块之后、任务列表之前，插入健康行（紧跟概览 tiles 容器结束标签后）：

```html
    <div v-if="props.health" class="queue-health" data-testid="queue-health">
      <span>活跃 worker：{{ props.health.active_worker_count }}</span>
      <span>最老等待：{{ props.health.oldest_pending_seconds }}s</span>
      <span>执行中：{{ props.health.running_count }}</span>
    </div>
```

- [ ] **步骤 3d：App.vue 加载并传入**

在 `apps/web/src/App.vue` 的 `loadTasks`（约第 157-171 行）改为同时取 health。把 `Promise.all` 数组与赋值改为：

```typescript
async function loadTasks() {
  try {
    const [list, summary, healthData] = await Promise.all([
      api.getTasks({ limit: 50 }),
      api.getTaskSummary(),
      api.getTaskHealth(),
    ])
    tasks.value = list.tasks || []
    taskSummary.value = summary
    taskHealth.value = healthData
  } catch (e: any) {
    if (!opportunitySummary.value && !currentJob.value) {
      error.value = '任务数据读取失败: ' + e.message
    }
  }
}
```

在 App.vue 的响应式声明区（`taskSummary` 声明处附近）加：

```typescript
const taskHealth = ref<TaskHealth | null>(null)
```

确保 App.vue 顶部从 `./types/job` 的 import 含 `TaskHealth`。在 `<TaskQueuePanel ...>`（约第 457-466 行）加 prop：

```html
        <TaskQueuePanel
          v-if="activeTab === 'tasks'"
          :summary="taskSummary"
          :tasks="tasks"
          :health="taskHealth"
          :busy-task-id="busyTaskId"
          @refresh="loadTasks"
          @cancel="cancelTask"
          @retry="retryTask"
          @select-job="selectJob"
        />
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd apps/web && npx vitest run src/__tests__/taskQueueViews.test.ts`
预期：全部 PASS（含现有用例）。
再跑类型检查：`cd apps/web && npx vue-tsc --noEmit`（若项目用此命令；否则 `npm run build`）预期无类型错误。

- [ ] **步骤 5：Commit**

```bash
git add apps/web/src/types/job.ts apps/web/src/services/api.ts apps/web/src/components/TaskQueuePanel.vue apps/web/src/App.vue apps/web/src/__tests__/taskQueueViews.test.ts
git commit -m "feat(web): 任务队列健康指标一行展示(A4c)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A5：常驻 worker 进程管理（launchd + systemd）

配置层任务，平台差异不进业务代码。共用启动命令：`python -m core.pipeline.task_worker --worker-id <id>`。

**文件（全部新建）：**
- 创建：`deploy/launchd/com.minifactory.worker.plist`
- 创建：`deploy/systemd/minifactory-worker@.service`
- 创建：`deploy/README.md`

- [ ] **步骤 1：创建 launchd plist（Mac）**

写 `deploy/launchd/com.minifactory.worker.plist`。注意 `__PROJECT_ROOT__` / `__PYTHON__` 为占位符，由 README 指引替换：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.minifactory.worker</string>
    <key>ProgramArguments</key>
    <array>
        <string>__PYTHON__</string>
        <string>-m</string>
        <string>core.pipeline.task_worker</string>
        <string>--worker-id</string>
        <string>worker-launchd-1</string>
    </array>
    <key>WorkingDirectory</key>
    <string>__PROJECT_ROOT__</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>PYTHONPATH</key>
        <string>__PROJECT_ROOT__</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>__PROJECT_ROOT__/data/runtime/logs/worker-launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>__PROJECT_ROOT__/data/runtime/logs/worker-launchd.err.log</string>
</dict>
</plist>
```

- [ ] **步骤 2：创建 systemd 模板单元（Linux）**

写 `deploy/systemd/minifactory-worker@.service`（`%i` 为实例名，起多个用 `@1 @2`）：

```ini
[Unit]
Description=MINI-factory task worker (%i)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/mini-factory
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/opt/mini-factory
ExecStart=/usr/bin/python3 -m core.pipeline.task_worker --worker-id worker-%i
Restart=always
RestartSec=3
StandardOutput=append:/opt/mini-factory/data/runtime/logs/worker-%i.out.log
StandardError=append:/opt/mini-factory/data/runtime/logs/worker-%i.err.log

[Install]
WantedBy=multi-user.target
```

- [ ] **步骤 3：创建 deploy/README.md**

写 `deploy/README.md`：

````markdown
# 部署：常驻 task worker

worker 启动命令两平台一致：

    python -m core.pipeline.task_worker --worker-id <id>

worker 自带 stale 回收（启动 + 周期，多 worker 经维护锁互斥），无需额外 cron。
日志统一写到 `data/runtime/logs/`。建议 2 个 worker 起步，最多 4 个。

## macOS（launchd）

1. 复制 `deploy/launchd/com.minifactory.worker.plist` 到 `~/Library/LaunchAgents/`。
2. 把文件里的 `__PYTHON__` 换成 `which python` 的输出，`__PROJECT_ROOT__` 换成项目绝对路径。
3. 起第二个 worker：复制一份改 `Label`（如 `com.minifactory.worker2`）和 `--worker-id`。
4. 加载与启动：

       launchctl load ~/Library/LaunchAgents/com.minifactory.worker.plist
       launchctl list | grep minifactory          # 确认在跑

5. 停止 / 卸载：

       launchctl unload ~/Library/LaunchAgents/com.minifactory.worker.plist

6. 看日志：`tail -f data/runtime/logs/worker-launchd.out.log`

KeepAlive=true：进程崩溃 launchd 自动拉起；RunAtLoad=true：登录即启动。

## Linux（systemd 模板单元）

1. 把项目放到 `/opt/mini-factory`（或改 service 里的路径）。
2. 复制 `deploy/systemd/minifactory-worker@.service` 到 `/etc/systemd/system/`。
3. 起 2 个 worker：

       sudo systemctl daemon-reload
       sudo systemctl enable --now minifactory-worker@1
       sudo systemctl enable --now minifactory-worker@2

4. 状态 / 日志：

       systemctl status minifactory-worker@1
       journalctl -u minifactory-worker@1 -f

5. 停止：`sudo systemctl stop minifactory-worker@1`

Restart=always：进程退出 3 秒后自动重启。需要 4 个 worker 就 `@3 @4`。

## 验证 worker 真在消费

    python -m core.runtime.task_store --summary    # 看 pending 是否被消费
````

- [ ] **步骤 4：验证配置语法**

运行（Mac 上验证 plist 合法）：`plutil -lint deploy/launchd/com.minifactory.worker.plist`
预期：`OK`。
systemd 单元无离线 lint，人工核对字段；确保 `data/runtime/logs/` 目录存在：
`mkdir -p data/runtime/logs`

- [ ] **步骤 5：Commit**

```bash
git add deploy/
git commit -m "feat(deploy): launchd+systemd 常驻 worker 配置(A5)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A6：A 阶段回归套件汇总验收

不写新逻辑，统一跑通规格要求的全部回归场景。

- [ ] **步骤 1：后端全量回归**

运行：`python -m pytest core/ apps/api/tests/ -q`
预期：全绿。逐项确认规格要求的场景有对应通过用例：
- generate_now 创建任务 → `apps/api/tests/test_queue_action_endpoint.py`
- cancel running/pending → `test_task_store.py::test_cancel_pending` + `test_task_worker.py::test_cancel_during_execution_not_completed`
- retry failed → `test_task_store.py::test_retry_failed_resets_to_pending`
- stale 回收 → `test_task_store.py::test_requeue_stale_running` + `test_task_worker.py::test_stale_recovery_runs_on_startup`
- 两 worker 并发不重复 → `test_task_store.py::test_concurrent_claim_no_duplicate`
- 同 queue_id 不重复 active → `test_task_store.py::test_find_active_by_queue_id_dedupes`

- [ ] **步骤 2：前端回归**

运行：`cd apps/web && npm test`
预期：全绿（含 health 行新用例）。

- [ ] **步骤 3：构建验证**

运行：`cd apps/web && npm run build`
预期：构建成功，无类型错误。

- [ ] **步骤 4：更新规格状态 + Commit**

把规格文件 `docs/superpowers/specs/2026-06-25-task-queue-hardening-design.md` 头部状态改为
`A 阶段已完成，B 阶段待评估`。

```bash
git add docs/superpowers/specs/2026-06-25-task-queue-hardening-design.md
git commit -m "docs(design): 标记任务队列改造 A 阶段完成(A6)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## B 阶段（仅计划，A 完成并评估后再实现，本轮不动手）

> B 阶段不在本计划的执行范围。以下为后续启动时的任务骨架，届时按同样的 TDD 粒度展开为完整步骤。

- **B1 指数退避 + jitter**：`core/runtime/task_models.py` 新增纯函数 `compute_backoff(attempts, base, cap, jitter, rng=random.random)`，`fail_task` 改用之；测试 `core/runtime/tests/test_task_models.py` 注入确定性 rng 断言区间与 cap。不与 A 混改。
- **B2 完整 task log 文件**：每任务 stdout/stderr 写 `data/runtime/logs/tasks/<task_id>.log`，成功失败都留，单文件大小上限 + 轮转。
- **B3 TTL 清理**：第一版只清过期日志或 dry-run 预览；若清 DB 仅限终态（succeeded/failed/cancelled），**永不碰 pending/running**。
- **B4 优先级老化**：后置；当前继续 `priority ASC, created_at ASC`，不引入有效优先级 SQL。

---

## 自检结果

**规格覆盖度：**
- 常驻 worker（launchd/systemd/共用命令/自动重启/日志）→ A5 ✅
- worker 内 stale 回收（启动 + 周期 + 维护锁 + 只碰超时 running）→ A1（锁）+ A2（回收）✅
- 2~4 worker + WAL（并发安全 + queue_id 去重）→ A3 ✅
- 最小健康指标（9 字段 + 接口 + 面板一行）→ A4a/A4b/A4c ✅
- 回归测试 6 场景 → A6 汇总 ✅

**占位符扫描：** 仅 deploy 配置内 `__PYTHON__`/`__PROJECT_ROOT__`/systemd `%i` 为有意占位符，README 已说明替换方式，非计划缺陷。无 TODO/待定。

**类型一致性：** `try_acquire_maintenance`（A1 定义 → A2 调用）签名一致；`health_summary`（A4a 定义 → A4b 调用）一致；`TaskHealth`（A4c types 定义 → api/panel/App 使用）字段一致；`MAINTENANCE_STALE_RECOVERY` 常量 A2 内自洽。





