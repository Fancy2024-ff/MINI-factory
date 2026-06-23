"""apps/api 队列动作接口测试（P0-2）+ 微信上传无产物路径（P0-3）。"""

from __future__ import annotations

import json


def _seed_queue(api, items):
    opp = api.OUTPUTS_DIR.parent / "opportunity"
    opp.mkdir(parents=True, exist_ok=True)
    api.OPPORTUNITY_DIR = opp
    (opp / "opportunity-queue.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return opp


def _queue():
    return [
        {"queue_id": "q-001", "feature_key": "app_store:1:ai_photo_retouch",
         "parent_app_key": "app_store:1", "selected_template": "ai-image", "status": "pending"},
        {"queue_id": "q-002", "feature_key": "app_store:1:avatar",
         "parent_app_key": "app_store:1", "selected_template": "avatar-viral", "status": "failed",
         "retry_count": 1},
    ]


def test_queue_action_requires_key(server_client):
    client, _ = server_client
    res = client.post("/api/opportunities/queue/action",
                      json={"action": "skip", "queue_id": "q-001"})
    assert res.status_code == 401


def test_queue_action_skip(server_client, auth_headers):
    client, api = server_client
    opp = _seed_queue(api, _queue())
    res = client.post("/api/opportunities/queue/action", headers=auth_headers,
                      json={"action": "skip", "queue_id": "q-001"})
    assert res.status_code == 200 and res.json()["ok"] is True
    queue = json.loads((opp / "opportunity-queue.json").read_text(encoding="utf-8"))
    item = next(i for i in queue if i["queue_id"] == "q-001")
    assert item["status"] == "skipped"


def test_queue_action_prioritize_moves_to_front(server_client, auth_headers):
    client, api = server_client
    opp = _seed_queue(api, _queue())
    res = client.post("/api/opportunities/queue/action", headers=auth_headers,
                      json={"action": "prioritize", "queue_id": "q-002"})
    assert res.status_code == 200
    queue = json.loads((opp / "opportunity-queue.json").read_text(encoding="utf-8"))
    assert queue[0]["queue_id"] == "q-002"
    assert queue[0]["priority_boosted"] is True


def test_queue_action_retry_resets_to_pending(server_client, auth_headers):
    client, api = server_client
    opp = _seed_queue(api, _queue())
    res = client.post("/api/opportunities/queue/action", headers=auth_headers,
                      json={"action": "retry", "queue_id": "q-002"})
    assert res.status_code == 200
    queue = json.loads((opp / "opportunity-queue.json").read_text(encoding="utf-8"))
    item = next(i for i in queue if i["queue_id"] == "q-002")
    assert item["status"] == "pending"


def test_queue_action_unknown_id_404(server_client, auth_headers):
    client, api = server_client
    _seed_queue(api, _queue())
    res = client.post("/api/opportunities/queue/action", headers=auth_headers,
                      json={"action": "skip", "queue_id": "nope"})
    assert res.status_code == 404


def test_queue_action_invalid_action_422(server_client, auth_headers):
    client, api = server_client
    _seed_queue(api, _queue())
    res = client.post("/api/opportunities/queue/action", headers=auth_headers,
                      json={"action": "bogus", "queue_id": "q-001"})
    assert res.status_code == 422  # Literal 校验失败


def test_generate_now_prioritizes_and_launches(server_client, auth_headers, monkeypatch):
    client, api = server_client
    opp = _seed_queue(api, _queue())

    # 不真正起子进程：mock Popen + 流式任务
    class _FakeProc:
        def poll(self):
            return None
        returncode = 0

    monkeypatch.setattr(api.subprocess, "Popen", lambda *a, **k: _FakeProc())

    async def _noop(job_id):
        return None
    monkeypatch.setattr(api, "_stream_pipeline_output", _noop)

    res = client.post("/api/opportunities/queue/action", headers=auth_headers,
                      json={"action": "generate_now", "queue_id": "q-002"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["accepted"] is True and body["mode"] == "queue"
    # q-002 被提到队首且为 pending（runner 会消费第一个 pending）
    queue = json.loads((opp / "opportunity-queue.json").read_text(encoding="utf-8"))
    assert queue[0]["queue_id"] == "q-002"
    assert queue[0]["status"] == "pending"
    # 清理：避免 fake proc 影响 teardown
    api.pipeline_process = None


def test_wechat_upload_no_dist_fails_cleanly(server_client, auth_headers):
    client, api = server_client
    # 配置完整但无构建产物 → 结构化失败，不抛异常、不泄密
    (api.PLATFORM_AUTH_DIR / "wechat.json").write_text(json.dumps({
        "appid": "wx_test", "private_key_path": str(api.PLATFORM_AUTH_DIR / "pk.key"),
        "upload_enabled": True,
    }), encoding="utf-8")
    (api.PLATFORM_AUTH_DIR / "pk.key").write_text("FAKE-DO-NOT-LEAK", encoding="utf-8")
    res = client.post("/api/platforms/wechat/upload", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["upload_passed"] is False
    # 失败原因结构化，不回显私钥内容
    assert "reason" in body
    assert "FAKE-DO-NOT-LEAK" not in json.dumps(body)
