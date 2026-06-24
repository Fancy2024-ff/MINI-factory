"""apps.api.main 鉴权 + 路由行为回归。

覆盖：写路由/下载需 API key、公共 GET、pipeline start 需 key 且不误启子进程、
artifact 路径穿越防御、WebSocket 缓冲历史日志。
"""

import json


# --- API key 鉴权 ---

def test_write_route_requires_api_key(server_client):
    client, _ = server_client
    res = client.post("/api/real-inputs/apps", json=[])
    assert res.status_code == 401


def test_download_requires_api_key(server_client):
    client, _ = server_client
    res = client.get("/api/jobs/whatever/download")
    assert res.status_code == 401


def test_download_with_key_missing_job_is_404(server_client, auth_headers):
    client, _ = server_client
    res = client.get("/api/jobs/does-not-exist/download", headers=auth_headers)
    assert res.status_code == 404


def test_status_route_is_public(server_client):
    client, _ = server_client
    res = client.get("/api/pipeline/status")
    assert res.status_code == 200
    assert "running" in res.json()


def test_pipeline_start_requires_api_key(server_client):
    client, _ = server_client
    # 无 key -> 401，且绝不能启动 pipeline 子进程
    res = client.post("/api/pipeline/start", json={"mode": "demo"})
    assert res.status_code == 401


def test_pipeline_start_defaults_async_enqueue(server_client, auth_headers):
    """/api/pipeline/start 默认 async：入队 task，返回 task_id/job_id，不直接同步执行。"""
    client, api = server_client
    res = client.post("/api/pipeline/start", headers=auth_headers, json={"mode": "queue"})
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["execution_mode"] == "async"
    assert body["kind"] == "pipeline.run"
    assert body["status"] == "pending"
    assert body["task_id"] and body["job_id"]
    # 没有起同步子进程
    assert api.pipeline_process is None
    # task 真的进了 task_store
    task = api._task_store().get_task(body["task_id"])
    assert task is not None and task["status"] == "pending"
    assert task["payload"]["mode"] == "queue"


def test_pipeline_start_crawl_maps_to_crawl_kind(server_client, auth_headers):
    """mode=crawl 入队为 opportunity.crawl 任务。"""
    client, api = server_client
    res = client.post("/api/pipeline/start", headers=auth_headers,
                      json={"mode": "crawl", "regions": "US", "platforms": "app_store"})
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "opportunity.crawl"
    task = api._task_store().get_task(body["task_id"])
    assert task["payload"]["regions"] == "US"


def test_pipeline_start_sync_compat(server_client, auth_headers, monkeypatch):
    """execution_mode=sync 走旧子进程模型（兼容/调试，非主路径）。"""
    client, api = server_client

    class _FakeProc:
        def poll(self):
            return None
        returncode = 0

    monkeypatch.setattr(api.subprocess, "Popen", lambda *a, **k: _FakeProc())

    async def _noop(job_id):
        return None
    monkeypatch.setattr(api, "_stream_pipeline_output", _noop)

    res = client.post("/api/pipeline/start", headers=auth_headers,
                      json={"mode": "queue", "execution_mode": "sync"})
    assert res.status_code == 200
    body = res.json()
    assert body["execution_mode"] == "sync"
    assert body["job_id"]
    # 同步模型下没有入队 task
    assert api._task_store().task_summary()["total"] == 0
    api.pipeline_process = None  # 清理


def test_pipeline_stop_requires_api_key(server_client):
    client, _ = server_client
    res = client.post("/api/pipeline/stop")
    assert res.status_code == 401


# --- 路径穿越防御 ---

def test_path_traversal_returns_403(server_client, auth_headers):
    client, server = server_client
    job_dir = server.OUTPUTS_DIR / "test-job-pt"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "candidate.json").write_text(json.dumps({"name": "test"}), encoding="utf-8")

    res = client.get("/api/jobs/test-job-pt/artifact?file=../../etc/passwd", headers=auth_headers)
    assert res.status_code == 403

    res = client.get("/api/jobs/test-job-pt/artifact?file=../../../etc/shadow", headers=auth_headers)
    assert res.status_code == 403

    # 合法文件可读
    res = client.get("/api/jobs/test-job-pt/artifact?file=candidate.json", headers=auth_headers)
    assert res.status_code == 200


# --- WebSocket 缓冲历史日志 ---

def test_ws_sends_buffered_history_logs(server_client, auth_headers):
    from collections import deque

    client, server = server_client
    server.pipeline_job_id = "ws-test-job"
    server.pipeline_process = None  # not running
    server.pipeline_logs = deque(["line1", "line2", "line3"], maxlen=5000)

    with client.websocket_connect("/ws/pipeline/ws-test-job?token=secret123") as ws:
        messages = []
        for _ in range(4):  # 3 log lines + 1 status
            messages.append(json.loads(ws.receive_text()))

    log_messages = [m for m in messages if m.get("type") == "step_log"]
    status_messages = [m for m in messages if m.get("type") == "status"]

    assert len(log_messages) == 3
    assert log_messages[0]["data"] == "line1"
    assert log_messages[2]["data"] == "line3"
    assert len(status_messages) == 1
    assert status_messages[0]["running"] is False

    server.pipeline_job_id = None
    server.pipeline_logs.clear()
