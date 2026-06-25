"""apps/api public generation 接口的限流测试。

/api/generation/image 与 /api/generation/template 是 public runtime 接口，会真实
调用 image provider（有成本），必须有基础防滥用限流。这里验证：
- 超过窗口内阈值后返回 {ok: false, error: {code: RATE_LIMITED, retryable: true}}，不抛 500
- 两个接口共享同一 IP 限流计数
- 限流不影响 dashboard 管理接口
全程 mock provider，不打真实网络。
"""

from __future__ import annotations


def _fake_ok(prompt, style="", aspect_ratio="1:1"):
    return {"image_url": None, "image_base64": "QUJD", "metadata": {}}


def _reset_rate(api, limit=3, window=60):
    """把限流阈值调小、清空计数，便于测试快速触发。"""
    api.GENERATION_RATE_LIMIT = limit
    api.GENERATION_RATE_WINDOW = window
    api._generation_calls.clear()


def test_image_endpoint_rate_limited_after_threshold(server_client, monkeypatch):
    client, api = server_client
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    _reset_rate(api, limit=3)

    # 前 3 次放行
    for _ in range(3):
        res = client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"})
        assert res.status_code == 200
        assert res.json()["ok"] is True

    # 第 4 次超限：结构化错误，非 500
    res = client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["retryable"] is True
    # 携带建议等待秒数，供前端按窗口退避，避免快重试持续打满限流（自锁死）。
    assert body["error"]["retry_after"] == api.GENERATION_RATE_WINDOW
    # 不暴露内部细节
    assert "deque" not in body["error"]["message"]
    assert "ip" not in body["error"]["message"].lower()


def test_template_endpoint_rate_limited_after_threshold(server_client, monkeypatch):
    client, api = server_client
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    _reset_rate(api, limit=2)

    for _ in range(2):
        res = client.post(
            "/api/generation/template",
            json={"template_id": "avatar-viral", "input": {"prompt": "短发女生"}},
        )
        assert res.json()["ok"] is True

    res = client.post(
        "/api/generation/template",
        json={"template_id": "avatar-viral", "input": {"prompt": "短发女生"}},
    )
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "RATE_LIMITED"


def test_rate_limit_shared_across_both_generation_endpoints(server_client, monkeypatch):
    """同一 IP 对两个 public 生成接口的调用计入同一限额。"""
    client, api = server_client
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    _reset_rate(api, limit=2)

    # image 用掉 1 次
    assert client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"}).json()["ok"] is True
    # template 用掉第 2 次
    assert client.post(
        "/api/generation/template",
        json={"template_id": "avatar-viral", "input": {"prompt": "x"}},
    ).json()["ok"] is True
    # 第 3 次（任一接口）应被限流
    res = client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"})
    assert res.json()["error"]["code"] == "RATE_LIMITED"


def test_rate_limit_does_not_affect_dashboard_endpoints(server_client, monkeypatch, auth_headers):
    """限流只作用于 public 生成接口，不影响 dashboard 管理接口。"""
    client, api = server_client
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    _reset_rate(api, limit=1)

    # 把生成接口刷到超限
    client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"})
    over = client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"})
    assert over.json()["error"]["code"] == "RATE_LIMITED"

    # dashboard 管理接口不受影响（带 key 正常 200）
    res = client.get("/api/overview", headers=auth_headers)
    assert res.status_code == 200
