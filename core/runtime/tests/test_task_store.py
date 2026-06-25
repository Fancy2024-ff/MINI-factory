"""core.runtime.task_store 测试：持久化队列的入队/领取/完成/失败/取消/重试/回收。

用临时文件库（非内存），覆盖 claim 并发不重复、重试 backoff、stale 回收等关键路径。
"""

from __future__ import annotations

import pytest

from core.runtime.task_store import TaskStore
from core.runtime.task_models import TaskKind, TaskStatus, now_iso


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.sqlite3", lock_seconds=600, backoff_seconds=30)


def test_enqueue_then_list_shows_pending(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, payload={"mode": "queue"})
    items = store.list_tasks(status=TaskStatus.PENDING)
    assert len(items) == 1
    assert items[0]["id"] == tid
    assert items[0]["status"] == TaskStatus.PENDING
    assert items[0]["payload"] == {"mode": "queue"}


def test_claim_marks_running(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    task = store.claim_next_task("worker-1")
    assert task["id"] == tid
    assert task["status"] == TaskStatus.RUNNING
    assert task["locked_by"] == "worker-1"
    assert task["attempts"] == 1
    assert task["started_at"] is not None


def test_two_claims_do_not_get_same_task(store):
    t1 = store.enqueue_task(TaskKind.PIPELINE_RUN, priority=50)
    t2 = store.enqueue_task(TaskKind.OPPORTUNITY_CRAWL, priority=100)
    c1 = store.claim_next_task("w1")
    c2 = store.claim_next_task("w2")
    assert {c1["id"], c2["id"]} == {t1, t2}
    assert c1["id"] != c2["id"]
    # 第三次没有可领取任务
    assert store.claim_next_task("w3") is None


def test_claim_respects_priority_then_created_order(store):
    low = store.enqueue_task(TaskKind.PIPELINE_RUN, priority=10)
    store.enqueue_task(TaskKind.PIPELINE_RUN, priority=200)
    # 优先级小的先被领取
    assert store.claim_next_task("w1")["id"] == low


def test_complete_sets_succeeded(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w1")
    task = store.complete_task(tid, result={"qa_passed": True})
    assert task["status"] == TaskStatus.SUCCEEDED
    assert task["result"] == {"qa_passed": True}
    assert task["finished_at"] is not None
    assert task["locked_by"] is None


def test_fail_retryable_under_max_returns_to_pending(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=3)
    store.claim_next_task("w1")  # attempts -> 1
    task = store.fail_task(tid, error_message="boom", retryable=True)
    assert task["status"] == TaskStatus.PENDING
    assert task["attempts"] == 1  # 已消耗一次
    assert task["next_run_at"] is not None
    assert task["locked_by"] is None


def test_fail_exhausts_attempts_then_failed(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=1)
    store.claim_next_task("w1")  # attempts -> 1, 已达 max
    task = store.fail_task(tid, error_message="boom", retryable=True)
    assert task["status"] == TaskStatus.FAILED
    assert task["finished_at"] is not None


def test_fail_non_retryable_goes_failed(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=5)
    store.claim_next_task("w1")
    task = store.fail_task(tid, error_message="bad", retryable=False)
    assert task["status"] == TaskStatus.FAILED


def test_cancel_pending(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    task = store.cancel_task(tid)
    assert task["status"] == TaskStatus.CANCELLED
    assert task["cancelled_at"] is not None
    # 已取消任务不会被领取
    assert store.claim_next_task("w1") is None


def test_retry_failed_resets_to_pending(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=1)
    store.claim_next_task("w1")
    store.fail_task(tid, retryable=True)  # -> failed (max reached)
    task = store.retry_task(tid)
    assert task["status"] == TaskStatus.PENDING
    assert task["attempts"] == 0  # 重置
    # 可被再次领取
    assert store.claim_next_task("w2")["id"] == tid


def test_requeue_stale_running(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w1")  # running, locked
    # 用未来时间触发回收（模拟 locked_until 已过期）
    from core.runtime.task_store import _add_seconds
    future = _add_seconds(now_iso(), 10_000)
    n = store.requeue_stale_tasks(now=future)
    assert n == 1
    task = store.get_task(tid)
    assert task["status"] == TaskStatus.PENDING
    assert task["locked_by"] is None
    assert task["error_code"] == "stale_lock_requeued"


def test_stale_requeue_does_not_touch_fresh_lock(store):
    store.enqueue_task(TaskKind.PIPELINE_RUN)
    store.claim_next_task("w1")
    # 用当前时间：锁未过期，不回收
    assert store.requeue_stale_tasks(now=now_iso()) == 0


def test_stale_exhausted_attempts_goes_failed(store):
    """attempts 已达 max_attempts 的 stale running 应标 failed，不是 pending（P2-2）。"""
    from core.runtime.task_store import _add_seconds

    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=1)
    store.claim_next_task("w1")  # attempts -> 1 == max
    future = _add_seconds(now_iso(), 10_000)
    stats = store.requeue_stale_tasks_detailed(now=future)
    assert stats == {"requeued": 0, "failed": 1}
    task = store.get_task(tid)
    assert task["status"] == TaskStatus.FAILED
    assert task["error_code"] == "stale_lock_exhausted"
    assert task["finished_at"] is not None


def test_stale_detailed_mixed_batch(store):
    """一批 stale：有余量的回 pending，达上限的 failed。"""
    from core.runtime.task_store import _add_seconds

    retryable = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=3)
    exhausted = store.enqueue_task(TaskKind.OPPORTUNITY_CRAWL, max_attempts=1)
    store.claim_next_task("w1")  # 领 retryable（prio 同，先到先得）
    store.claim_next_task("w1")  # 领 exhausted
    future = _add_seconds(now_iso(), 10_000)
    stats = store.requeue_stale_tasks_detailed(now=future)
    assert stats == {"requeued": 1, "failed": 1}
    assert store.get_task(retryable)["status"] == TaskStatus.PENDING
    assert store.get_task(exhausted)["status"] == TaskStatus.FAILED


def test_requeue_stale_int_wrapper_compat(store):
    """旧 requeue_stale_tasks 仍返回 int（被回收数），保持兼容。"""
    from core.runtime.task_store import _add_seconds

    store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=3)
    store.claim_next_task("w1")
    future = _add_seconds(now_iso(), 10_000)
    n = store.requeue_stale_tasks(now=future)
    assert n == 1


def test_get_status_and_is_cancelled(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN)
    assert store.get_status(tid) == TaskStatus.PENDING
    assert store.is_cancelled(tid) is False
    store.cancel_task(tid)
    assert store.is_cancelled(tid) is True
    assert store.get_status("nope") is None


def test_summary_counts(store):
    store.enqueue_task(TaskKind.PIPELINE_RUN)
    t2 = store.enqueue_task(TaskKind.OPPORTUNITY_CRAWL)
    store.claim_next_task("w1")
    store.claim_next_task("w1")
    store.complete_task(t2, result={})
    summary = store.task_summary()
    assert summary["total"] == 2
    assert summary["by_status"][TaskStatus.SUCCEEDED] == 1
    assert summary["by_status"][TaskStatus.RUNNING] == 1
    assert summary["by_kind"][TaskKind.OPPORTUNITY_CRAWL] == 1


def test_error_message_sanitized_on_fail(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, max_attempts=1)
    store.claim_next_task("w1")
    task = store.fail_task(
        tid, error_message="boom api_key=SECRET_LEAK_VALUE here", retryable=False
    )
    assert "SECRET_LEAK_VALUE" not in (task["error_message"] or "")


def test_unknown_kind_rejected(store):
    with pytest.raises(ValueError):
        store.enqueue_task("bogus.kind")


# --- queue_id / job_id 映射与去重 ---

def test_enqueue_with_queue_and_job_id(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, queue_id="q-1", job_id="j-1")
    task = store.get_task(tid)
    assert task["queue_id"] == "q-1"
    assert task["job_id"] == "j-1"


def test_find_active_by_queue_id(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_RUN, queue_id="q-1")
    active = store.find_active_by_queue_id("q-1")
    assert active is not None and active["id"] == tid
    # running 也算 active
    store.claim_next_task("w1")
    assert store.find_active_by_queue_id("q-1")["id"] == tid
    # 完成后不再 active
    store.complete_task(tid, result={})
    assert store.find_active_by_queue_id("q-1") is None


def test_find_active_by_queue_id_none_for_unknown(store):
    assert store.find_active_by_queue_id("nope") is None


def test_find_active_by_job_id(store):
    tid = store.enqueue_task(TaskKind.PIPELINE_AUTO, job_id="j-9")
    assert store.find_active_by_job_id("j-9")["id"] == tid
    store.cancel_task(tid)
    assert store.find_active_by_job_id("j-9") is None


def test_list_tasks_filter_by_queue_and_job(store):
    store.enqueue_task(TaskKind.PIPELINE_RUN, queue_id="q-1", job_id="j-1")
    store.enqueue_task(TaskKind.OPPORTUNITY_CRAWL)
    assert len(store.list_tasks(queue_id="q-1")) == 1
    assert len(store.list_tasks(job_id="j-1")) == 1
    assert len(store.list_tasks(queue_id="other")) == 0


def test_legacy_db_migration(tmp_path):
    """旧库（无 queue_id/job_id 列）打开后自动迁移，仍可用。"""
    import sqlite3
    db = tmp_path / "old.sqlite3"
    c = sqlite3.connect(str(db))
    c.execute(
        """CREATE TABLE tasks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
           priority INTEGER NOT NULL DEFAULT 100, payload_json TEXT NOT NULL DEFAULT '{}',
           result_json TEXT, error_code TEXT, error_message TEXT, attempts INTEGER NOT NULL DEFAULT 0,
           max_attempts INTEGER NOT NULL DEFAULT 3, locked_by TEXT, locked_until TEXT, next_run_at TEXT,
           created_at TEXT NOT NULL, updated_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
           cancelled_at TEXT)"""
    )
    c.execute("INSERT INTO tasks (id,kind,status,created_at,updated_at) "
              "VALUES ('old1','pipeline.run','succeeded','2026-01-01','2026-01-01')")
    c.commit()
    c.close()

    s = TaskStore(db)
    tid = s.enqueue_task(TaskKind.PIPELINE_RUN, queue_id="q-new", job_id="j-new")
    assert s.get_task(tid)["queue_id"] == "q-new"
    assert s.get_task("old1")["queue_id"] is None  # 旧行迁移后列为 NULL


# --- A1: 维护抢占锁 queue_maintenance ---

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


def test_maintenance_lock_concurrent_single_winner(tmp_path):
    import threading
    store = TaskStore(tmp_path / "tasks.sqlite3")
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


# --- A3: 多 worker 并发安全 + queue_id 去重 ---

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
    """同 queue_id 已有 active(pending) task 时命中，用于去重；完成后不再 active。"""
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
