"""apps/api 任务系统接口测试：summary / list / get / cancel / retry / requeue / enqueue。

复用 server_client fixture（已隔离 TASK_DB_PATH 到 tmp）。
"""

from __future__ import annotations


def _enqueue(client, auth_headers, kind="pipeline.run", payload=None, priority=100):
    res = client.post("/api/pipeline/enqueue", headers=auth_headers,
                      json={"kind": kind, "payload": payload or {}, "priority": priority})
    assert res.status_code == 200
    return res.json()["task_id"]


def test_tasks_summary_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/tasks/summary").status_code == 401


def test_enqueue_and_summary(server_client, auth_headers):
    client, _ = server_client
    _enqueue(client, auth_headers, payload={"mode": "queue"})
    res = client.get("/api/tasks/summary", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["by_status"]["pending"] == 1


def test_list_tasks(server_client, auth_headers):
    client, _ = server_client
    _enqueue(client, auth_headers)
    _enqueue(client, auth_headers, kind="opportunity.crawl")
    res = client.get("/api/tasks", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["count"] == 2
    # 过滤 kind
    res2 = client.get("/api/tasks?kind=opportunity.crawl", headers=auth_headers)
    assert res2.json()["count"] == 1


def test_get_task_detail_and_404(server_client, auth_headers):
    client, _ = server_client
    tid = _enqueue(client, auth_headers)
    res = client.get(f"/api/tasks/{tid}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == tid
    assert client.get("/api/tasks/nope", headers=auth_headers).status_code == 404


def test_cancel_pending_task(server_client, auth_headers):
    client, _ = server_client
    tid = _enqueue(client, auth_headers)
    res = client.post(f"/api/tasks/{tid}/cancel", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"


def test_cancel_unknown_404(server_client, auth_headers):
    client, _ = server_client
    assert client.post("/api/tasks/nope/cancel", headers=auth_headers).status_code == 404


def test_retry_failed_task(server_client, auth_headers):
    client, api = server_client
    tid = _enqueue(client, auth_headers)
    # 直接用 store 把任务推到 failed
    store = api._task_store()
    store.claim_next_task("w1")
    store.fail_task(tid, retryable=False)
    assert store.get_task(tid)["status"] == "failed"
    res = client.post(f"/api/tasks/{tid}/retry", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "pending"


def test_requeue_stale_endpoint(server_client, auth_headers):
    client, api = server_client
    tid = _enqueue(client, auth_headers)
    store = api._task_store()
    store.claim_next_task("w1")
    # 锁未过期时不回收；返回 requeued + failed 两个字段（P2-2）
    res0 = client.post("/api/tasks/maintenance/requeue-stale", headers=auth_headers)
    body = res0.json()
    assert body["requeued"] == 0
    assert body["failed"] == 0
    assert store.get_task(tid)["status"] == "running"


def test_enqueue_with_payload_mode(server_client, auth_headers):
    client, api = server_client
    res = client.post("/api/pipeline/enqueue", headers=auth_headers,
                      json={"kind": "pipeline.run", "payload": {"mode": "demo"}})
    assert res.status_code == 200
    tid = res.json()["task_id"]
    task = api._task_store().get_task(tid)
    assert task["payload"]["mode"] == "demo"


def test_enqueue_requires_key(server_client):
    client, _ = server_client
    res = client.post("/api/pipeline/enqueue", json={"kind": "pipeline.run"})
    assert res.status_code == 401


def test_enqueue_invalid_kind_422(server_client, auth_headers):
    client, _ = server_client
    res = client.post("/api/pipeline/enqueue", headers=auth_headers,
                      json={"kind": "bogus"})
    assert res.status_code == 422


def test_enqueue_with_queue_id_dedupes(server_client, auth_headers):
    """带 queue_id 的 enqueue 会去重：同一 queue_id 已有 active task 时复用。"""
    client, api = server_client
    r1 = client.post("/api/pipeline/enqueue", headers=auth_headers,
                     json={"kind": "pipeline.run", "payload": {"queue_id": "q-X", "mode": "queue"}}).json()
    r2 = client.post("/api/pipeline/enqueue", headers=auth_headers,
                     json={"kind": "pipeline.run", "payload": {"queue_id": "q-X", "mode": "queue"}}).json()
    assert r1["reused"] is False and r2["reused"] is True
    assert r1["task_id"] == r2["task_id"]
    assert len(api._task_store().list_tasks(queue_id="q-X")) == 1


def test_enqueue_pipeline_run_assigns_job_id(server_client, auth_headers):
    """pipeline.run 未带 job_id 时自动预分配，便于 task↔job 追踪。"""
    client, api = server_client
    body = client.post("/api/pipeline/enqueue", headers=auth_headers,
                       json={"kind": "pipeline.run", "payload": {"mode": "queue"}}).json()
    assert body["job_id"]
    task = api._task_store().get_task(body["task_id"])
    assert task["job_id"] == body["job_id"]


def test_list_tasks_filter_by_queue_and_job(server_client, auth_headers):
    client, api = server_client
    b1 = client.post("/api/pipeline/enqueue", headers=auth_headers,
                     json={"kind": "pipeline.run", "payload": {"queue_id": "q-1", "mode": "queue"}}).json()
    client.post("/api/pipeline/enqueue", headers=auth_headers,
                json={"kind": "opportunity.crawl", "payload": {}})

    # filter by queue_id
    r = client.get("/api/tasks?queue_id=q-1", headers=auth_headers)
    assert r.json()["count"] == 1
    # by-queue endpoint
    rq = client.get("/api/tasks/by-queue/q-1", headers=auth_headers)
    assert rq.status_code == 200 and rq.json()["count"] == 1
    # by-job endpoint
    rj = client.get(f"/api/tasks/by-job/{b1['job_id']}", headers=auth_headers)
    assert rj.status_code == 200 and rj.json()["count"] == 1


def test_start_async_and_enqueue_share_store(server_client, auth_headers):
    """start(async) 与 enqueue 落到同一 task_store（统一执行模型）。"""
    client, api = server_client
    client.post("/api/pipeline/start", headers=auth_headers, json={"mode": "queue"})
    client.post("/api/pipeline/enqueue", headers=auth_headers,
                json={"kind": "opportunity.crawl", "payload": {}})
    summary = client.get("/api/tasks/summary", headers=auth_headers).json()
    assert summary["total"] == 2
    assert summary["by_kind"]["pipeline.run"] == 1
    assert summary["by_kind"]["opportunity.crawl"] == 1
