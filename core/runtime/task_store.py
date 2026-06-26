"""core.runtime.task_store — 持久化任务队列（Python 标准库 sqlite3）。

属于运行时基础设施。提供一个生产级 MVP 任务队列：持久化、状态可追踪、优先级、
重试、取消、worker claim/lock（避免多 worker 抢同一任务）、stale lock 回收。

设计取舍：
- 仅用标准库 sqlite3，不引入 Celery / Redis / PostgreSQL。
- WAL 模式 + busy_timeout，claim 用 BEGIN IMMEDIATE 写事务串行化，保证两个 worker
  不会 claim 到同一个任务。
- 单文件 DB，默认 data/runtime/tasks.sqlite3（已在 .gitignore）。

执行逻辑不在这里（见 core.pipeline.task_worker）；状态常量/流转见 task_models。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from core.runtime import task_models as tm
from core.runtime.task_models import TaskStatus, TaskKind

# 默认任务库路径（runtime 基础设施数据目录）。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "runtime" / "tasks.sqlite3"

# 锁默认租约（秒）：claim 时 locked_until = now + 该时长；worker 用 heartbeat 续租。
DEFAULT_LOCK_SECONDS = 600
# 失败重试默认 backoff（秒）：fail 可重试时 next_run_at = now + backoff。
DEFAULT_BACKOFF_SECONDS = 30


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 100,
    payload_json  TEXT NOT NULL DEFAULT '{}',
    result_json   TEXT,
    error_code    TEXT,
    error_message TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 3,
    locked_by     TEXT,
    locked_until  TEXT,
    next_run_at   TEXT,
    queue_id      TEXT,
    job_id        TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    cancelled_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks (status, priority, next_run_at);
CREATE INDEX IF NOT EXISTS idx_tasks_locked_until ON tasks (locked_until);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks (created_at);

CREATE TABLE IF NOT EXISTS queue_maintenance (
    name        TEXT PRIMARY KEY,
    last_run_at TEXT,
    runner      TEXT
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id   TEXT PRIMARY KEY,
    last_seen   TEXT NOT NULL,
    started_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_state (
    alert_key         TEXT PRIMARY KEY,
    last_fired_at     TEXT,
    active            INTEGER NOT NULL DEFAULT 0,
    recover_confirms  INTEGER NOT NULL DEFAULT 0,
    last_recovered_at TEXT
);
"""

# queue_id / job_id 是后加的列；旧库需 ALTER 补列（sqlite 无 IF NOT EXISTS for column）。
_MIGRATIONS = (
    ("queue_id", "ALTER TABLE tasks ADD COLUMN queue_id TEXT"),
    ("job_id", "ALTER TABLE tasks ADD COLUMN job_id TEXT"),
)

# 依赖后加列的索引：必须在 _MIGRATIONS 补列之后再建（否则旧库报 no such column）。
_POST_MIGRATION_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_tasks_queue_id ON tasks (queue_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks (job_id)",
)

def _add_seconds(iso_ts: str, seconds: int) -> str:
    """在 ISO 时间戳上加 N 秒，返回 ISO 字符串（UTC）。"""
    from datetime import datetime, timedelta

    dt = datetime.fromisoformat(iso_ts)
    return (dt + timedelta(seconds=seconds)).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """把 sqlite Row 转成 dict，并反序列化 payload/result JSON 字段。"""
    d = dict(row)
    d["payload"] = tm.loads(d.get("payload_json"))
    d["result"] = tm.loads(d.get("result_json")) if d.get("result_json") else None
    return d


class TaskStore:
    """SQLite 任务队列。线程/进程安全靠 WAL + BEGIN IMMEDIATE 写事务。

    用法：
        store = TaskStore()              # 默认 data/runtime/tasks.sqlite3
        store = TaskStore(":memory:")    # 测试可用内存库（注意：内存库不跨连接）
        store = TaskStore(tmp / "t.db")  # 指定路径

    每次操作打开一个短连接（除内存库外），避免长连接在多线程下的复杂度。
    """

    def __init__(self, db_path: str | Path | None = None, lock_seconds: int = DEFAULT_LOCK_SECONDS,
                 backoff_seconds: int = DEFAULT_BACKOFF_SECONDS):
        self.db_path = ":memory:" if db_path == ":memory:" else Path(db_path or DEFAULT_DB_PATH)
        self.lock_seconds = lock_seconds
        self.backoff_seconds = backoff_seconds
        self._mem_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            # 内存库必须复用同一连接，否则数据不可见。
            self._mem_conn = self._new_connection()
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    # --- 连接管理 ---

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path if self.db_path == ":memory:" else str(self.db_path),
            timeout=30.0,
            isolation_level=None,  # 自己管理事务（BEGIN/COMMIT 显式发）
            check_same_thread=False,  # 后台 heartbeat 线程会跨线程用连接（内存库共享连接）
        )
        conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _conn(self) -> sqlite3.Connection:
        return self._mem_conn if self._mem_conn is not None else self._new_connection()

    def _close(self, conn: sqlite3.Connection) -> None:
        # 内存库连接需保活；文件库连接用完即关。
        if self._mem_conn is None:
            conn.close()

    def init_schema(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(_SCHEMA)
            # 旧库迁移：补 queue_id / job_id 列（已存在则忽略 OperationalError）。
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
            for col, ddl in _MIGRATIONS:
                if col not in existing:
                    try:
                        conn.execute(ddl)
                    except sqlite3.OperationalError:
                        pass  # 并发迁移竞态：列已被另一个连接加上
            # 补列后再建依赖这些列的索引。
            for ddl in _POST_MIGRATION_INDEXES:
                conn.execute(ddl)
        finally:
            self._close(conn)

    # --- 写操作 ---

    def enqueue_task(
        self,
        kind: str,
        payload: dict | None = None,
        priority: int = 100,
        max_attempts: int = 3,
        task_id: str | None = None,
        queue_id: str | None = None,
        job_id: str | None = None,
    ) -> str:
        """入队一个新任务（status=pending，可立即被 claim）。返回 task_id。

        queue_id / job_id 提为一等列（除了存在 payload 里），用于 task↔queue item↔job
        三者映射与活跃任务去重查询（find_active_by_queue_id）。
        """
        if kind not in TaskKind.ALL:
            raise ValueError(f"未知 task kind: {kind}（合法：{TaskKind.ALL}）")
        tid = task_id or uuid.uuid4().hex
        ts = tm.now_iso()
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO tasks (id, kind, status, priority, payload_json, attempts,
                                   max_attempts, queue_id, job_id, next_run_at,
                                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (tid, kind, TaskStatus.PENDING, priority, tm.dumps(payload),
                 max_attempts, queue_id, job_id, ts, ts, ts),
            )
        finally:
            self._close(conn)
        return tid

    def find_active_by_queue_id(self, queue_id: str) -> dict | None:
        """返回该 queue_id 当前 active（pending/running）的任务（最新一个），无则 None。

        用于 generate_now 去重：同一 queue item 已有 active task 时不重复创建。
        """
        conn = self._conn()
        try:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE queue_id = ? AND status IN (?, ?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (queue_id, TaskStatus.PENDING, TaskStatus.RUNNING),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            self._close(conn)

    def find_active_by_job_id(self, job_id: str) -> dict | None:
        """返回该 job_id 当前 active（pending/running）的任务（最新一个），无则 None。"""
        conn = self._conn()
        try:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE job_id = ? AND status IN (?, ?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_id, TaskStatus.PENDING, TaskStatus.RUNNING),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            self._close(conn)

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

    def worker_heartbeat(self, worker_id: str, now: str | None = None) -> None:
        """worker 心跳：upsert 自己的 last_seen。无论有无任务都调，证明进程活着。"""
        now = now or tm.now_iso()
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO workers (worker_id, last_seen, started_at)
                VALUES (?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (worker_id, now, now),
            )
        finally:
            self._close(conn)

    def list_active_workers(self, timeout_seconds: int, now: str | None = None) -> list[dict]:
        """last_seen 在 now-timeout 之内的 worker（视为存活）。"""
        now = now or tm.now_iso()
        threshold = _add_seconds(now, -timeout_seconds)
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT worker_id, last_seen, started_at FROM workers WHERE last_seen > ?",
                (threshold,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close(conn)

    def count_active_workers(self, timeout_seconds: int, now: str | None = None) -> int:
        """存活 worker 数（last_seen > now-timeout）。"""
        return len(self.list_active_workers(timeout_seconds, now=now))

    def get_alert_state(self, alert_key: str) -> dict | None:
        """读告警状态行；不存在返回 None。"""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM alert_state WHERE alert_key = ?", (alert_key,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            self._close(conn)

    def upsert_alert_state(self, alert_key: str, **fields) -> None:
        """插入/部分更新告警状态。只更新传入的字段（其余保留原值）。

        允许字段：last_fired_at / active / recover_confirms / last_recovered_at。
        """
        allowed = {"last_fired_at", "active", "recover_confirms", "last_recovered_at"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown alert_state fields: {bad}")
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM alert_state WHERE alert_key = ?", (alert_key,)
            ).fetchone()
            if exists is None:
                conn.execute(
                    "INSERT INTO alert_state (alert_key, active, recover_confirms) VALUES (?, 0, 0)",
                    (alert_key,),
                )
            if fields:
                cols = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE alert_state SET {cols} WHERE alert_key = ?",
                    (*fields.values(), alert_key),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)

    def claim_next_task(self, worker_id: str, lock_seconds: int | None = None) -> dict | None:
        """原子领取下一个可执行任务。无可领取任务时返回 None。

        规则：
        - 只 claim status=pending 且 next_run_at <= now 的任务。
        - attempts < max_attempts（已达上限的不再领取）。
        - 排序 priority ASC, created_at ASC（小优先级先跑，同级先到先服务）。
        - 在一个 BEGIN IMMEDIATE 写事务内 select+update，保证并发 worker 不抢同一个。
        - claim 时 status=running, locked_by, locked_until=now+lock, started_at, attempts+1。
        """
        lock_s = lock_seconds if lock_seconds is not None else self.lock_seconds
        now = tm.now_iso()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                  AND attempts < max_attempts
                  AND (next_run_at IS NULL OR next_run_at <= ?)
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
                (TaskStatus.PENDING, now),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            locked_until = _add_seconds(now, lock_s)
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, locked_by = ?, locked_until = ?, started_at = ?,
                    attempts = attempts + 1, updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.RUNNING, worker_id, locked_until, now, now, row["id"]),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
        return self.get_task(row["id"])

    def heartbeat_task(self, task_id: str, worker_id: str, lock_seconds: int | None = None) -> bool:
        """worker 续租锁（延长 locked_until）。仅当任务仍 running 且锁属于该 worker 时生效。

        返回 True 表示续租成功；False 表示任务已不归该 worker（被取消/回收/完成）。
        """
        lock_s = lock_seconds if lock_seconds is not None else self.lock_seconds
        now = tm.now_iso()
        conn = self._conn()
        try:
            cur = conn.execute(
                """
                UPDATE tasks
                SET locked_until = ?, updated_at = ?
                WHERE id = ? AND status = ? AND locked_by = ?
                """,
                (_add_seconds(now, lock_s), now, task_id, TaskStatus.RUNNING, worker_id),
            )
            return cur.rowcount > 0
        finally:
            self._close(conn)

    def complete_task(self, task_id: str, result: dict | None = None) -> dict | None:
        """标记任务成功（running -> succeeded）。返回更新后的任务。"""
        now = tm.now_iso()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            if not tm.can_transition(row["status"], TaskStatus.SUCCEEDED):
                conn.execute("COMMIT")
                return self.get_task(task_id)
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, result_json = ?, finished_at = ?, updated_at = ?,
                    locked_by = NULL, locked_until = NULL, error_code = NULL, error_message = NULL
                WHERE id = ?
                """,
                (TaskStatus.SUCCEEDED, tm.dumps(result), now, now, task_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
        return self.get_task(task_id)

    def fail_task(
        self,
        task_id: str,
        error_code: str = "task_error",
        error_message: str = "",
        retryable: bool = True,
        backoff_seconds: int | None = None,
    ) -> dict | None:
        """标记任务失败。

        - 若 retryable 且 attempts < max_attempts：status=pending，next_run_at=now+backoff
          （回队等待重试，attempts 已在 claim 时自增）。
        - 否则：status=failed，finished_at=now（终态）。
        - error_message 经脱敏后入库（不泄露密钥）。
        """
        backoff = backoff_seconds if backoff_seconds is not None else self.backoff_seconds
        now = tm.now_iso()
        safe_msg = tm.sanitize_error(error_message)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, attempts, max_attempts FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            can_retry = retryable and row["attempts"] < row["max_attempts"]
            target = TaskStatus.PENDING if can_retry else TaskStatus.FAILED
            if not tm.can_transition(row["status"], target):
                conn.execute("COMMIT")
                return self.get_task(task_id)
            if can_retry:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, error_code = ?, error_message = ?, next_run_at = ?,
                        locked_by = NULL, locked_until = NULL, started_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.PENDING, error_code, safe_msg, _add_seconds(now, backoff),
                     now, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, error_code = ?, error_message = ?, finished_at = ?,
                        locked_by = NULL, locked_until = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.FAILED, error_code, safe_msg, now, now, task_id),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
        return self.get_task(task_id)

    def cancel_task(self, task_id: str) -> dict | None:
        """取消任务（pending/running/failed -> cancelled）。终态(成功/已取消)不可取消。"""
        now = tm.now_iso()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            if not tm.can_transition(row["status"], TaskStatus.CANCELLED):
                conn.execute("COMMIT")
                return self.get_task(task_id)
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, cancelled_at = ?, finished_at = ?, updated_at = ?,
                    locked_by = NULL, locked_until = NULL
                WHERE id = ?
                """,
                (TaskStatus.CANCELLED, now, now, now, task_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
        return self.get_task(task_id)

    def retry_task(self, task_id: str, reset_attempts: bool = True) -> dict | None:
        """手动重试一个 failed 任务（failed -> pending）。

        reset_attempts=True 时把 attempts 归零，让任务获得全新的 max_attempts 次机会。
        """
        now = tm.now_iso()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            if not tm.can_transition(row["status"], TaskStatus.PENDING):
                conn.execute("COMMIT")
                return self.get_task(task_id)
            if reset_attempts:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, attempts = 0, next_run_at = ?, error_code = NULL,
                        error_message = NULL, finished_at = NULL, started_at = NULL,
                        locked_by = NULL, locked_until = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.PENDING, now, now, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, next_run_at = ?, finished_at = NULL, started_at = NULL,
                        locked_by = NULL, locked_until = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.PENDING, now, now, task_id),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
        return self.get_task(task_id)

    def requeue_stale_tasks_detailed(self, now: str | None = None) -> dict:
        """回收 stale running 任务（locked_until 已过期），按剩余尝试次数分流。

        worker 崩溃/卡死锁未释放时使用。分两种处理：
        - attempts < max_attempts：回 pending（error_code=stale_lock_requeued），可被重新 claim。
        - attempts >= max_attempts：标 failed（error_code=stale_lock_exhausted，finished_at=now），
          避免出现「pending 却永远不会被 claim」的误导态。
        attempts 不回退（已消耗），由 max_attempts 兜底防止无限重试。
        返回 {"requeued": n, "failed": m}。
        """
        now = now or tm.now_iso()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 1) 已达上限的 stale running → failed（终态）。
            failed_cur = conn.execute(
                """
                UPDATE tasks
                SET status = ?, locked_by = NULL, locked_until = NULL,
                    error_code = 'stale_lock_exhausted',
                    error_message = 'lock expired and max_attempts reached',
                    finished_at = ?, updated_at = ?
                WHERE status = ? AND locked_until IS NOT NULL AND locked_until <= ?
                  AND attempts >= max_attempts
                """,
                (TaskStatus.FAILED, now, now, TaskStatus.RUNNING, now),
            )
            failed_n = failed_cur.rowcount
            # 2) 仍有尝试余量的 stale running → pending（可重新 claim）。
            requeued_cur = conn.execute(
                """
                UPDATE tasks
                SET status = ?, locked_by = NULL, locked_until = NULL, started_at = NULL,
                    next_run_at = ?, error_code = 'stale_lock_requeued', updated_at = ?
                WHERE status = ? AND locked_until IS NOT NULL AND locked_until <= ?
                  AND attempts < max_attempts
                """,
                (TaskStatus.PENDING, now, now, TaskStatus.RUNNING, now),
            )
            requeued_n = requeued_cur.rowcount
            conn.execute("COMMIT")
            return {"requeued": requeued_n, "failed": failed_n}
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)

    def requeue_stale_tasks(self, now: str | None = None) -> int:
        """回收 stale running 任务。返回被回收（重新 pending）的任务数。

        薄封装 requeue_stale_tasks_detailed，保持旧返回类型（int）兼容；需要 failed
        统计请用 requeue_stale_tasks_detailed。
        """
        return self.requeue_stale_tasks_detailed(now=now)["requeued"]

    # --- 读操作 ---

    def get_task(self, task_id: str) -> dict | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            self._close(conn)

    def get_status(self, task_id: str) -> str | None:
        """轻量读取任务状态（不反序列化 payload/result），供 worker 频繁轮询 cancel。"""
        conn = self._conn()
        try:
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return row["status"] if row else None
        finally:
            self._close(conn)

    def is_cancelled(self, task_id: str) -> bool:
        """任务是否已被取消（worker 执行期间用来感知 cancel）。"""
        return self.get_status(task_id) == TaskStatus.CANCELLED

    def list_tasks(
        self,
        status: str | None = None,
        kind: str | None = None,
        queue_id: str | None = None,
        job_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """列出任务（默认按 created_at 倒序，最新在前）。可按 status/kind/queue_id/job_id 过滤。"""
        clauses = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if queue_id:
            clauses.append("queue_id = ?")
            params.append(queue_id)
        if job_id:
            clauses.append("job_id = ?")
            params.append(job_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        conn = self._conn()
        try:
            rows = conn.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            self._close(conn)

    def task_summary(self) -> dict:
        """按状态聚合统计 + 总数，供 dashboard / CLI 概览。"""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ).fetchall()
            by_status = {s: 0 for s in TaskStatus.ALL}
            for r in rows:
                by_status[r["status"]] = r["n"]
            total = sum(by_status.values())
            kind_rows = conn.execute(
                "SELECT kind, COUNT(*) AS n FROM tasks GROUP BY kind"
            ).fetchall()
            by_kind = {r["kind"]: r["n"] for r in kind_rows}
            return {"total": total, "by_status": by_status, "by_kind": by_kind}
        finally:
            self._close(conn)

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


# --- 模块级单例（默认库），供 API / worker 复用 ---
_default_store: TaskStore | None = None


def get_default_store() -> TaskStore:
    """返回默认任务库（data/runtime/tasks.sqlite3）的进程内单例。"""
    global _default_store
    if _default_store is None:
        _default_store = TaskStore()
    return _default_store


def _cli() -> None:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="task_store CLI：查看/演练任务队列")
    parser.add_argument("--db", default=None, help="任务库路径（默认 data/runtime/tasks.sqlite3）")
    parser.add_argument("--summary", action="store_true", help="打印任务统计")
    parser.add_argument("--list", action="store_true", help="列出最近任务")
    parser.add_argument("--enqueue-test", action="store_true",
                        help="入队一个 pipeline.run 测试任务（演练用）")
    args = parser.parse_args()

    store = TaskStore(args.db)
    if args.enqueue_test:
        tid = store.enqueue_task(
            TaskKind.PIPELINE_RUN,
            payload={"mode": "queue"},
            priority=100,
        )
        print(f"[task_store] enqueued test task: {tid}")
    if args.list:
        for t in store.list_tasks(limit=20):
            print(f"  {t['id'][:12]} {t['kind']:<18} {t['status']:<10} "
                  f"prio={t['priority']} attempts={t['attempts']}/{t['max_attempts']}")
    if args.summary or not (args.enqueue_test or args.list):
        print(_json.dumps(store.task_summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
