"""apps/api /api/generation/template endpoint 测试。

权限边界：runtime/public 接口，无需 dashboard key（即便 server_client 已配置 key）。
全程 mock image provider，不打真实网络。
"""

from __future__ import annotations


def _fake_ok(prompt, style="", aspect_ratio="1:1"):
    return {"image_url": None, "image_base64": "QUJD", "metadata": {}}


def test_template_public_no_dashboard_key(server_client, monkeypatch):
    client, _ = server_client  # fixture 已设 DASHBOARD_API_KEY
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    res = client.post(
        "/api/generation/template",
        json={"template_id": "avatar-viral", "input": {"prompt": "短发女生", "style": "business"}},
    )
    assert res.status_code == 200, "runtime 接口不应要求 dashboard 鉴权"
    body = res.json()
    assert body["ok"] is True
    assert body["template_id"] == "avatar-viral"
    assert body["preview_type"] == "avatar"
    assert body["result"]["title"] == "AI 头像已生成"
    assert body["result"]["image_base64"] == "QUJD"


def test_template_unsupported_rejected(server_client):
    client, _ = server_client
    res = client.post(
        "/api/generation/template",
        json={"template_id": "sticker-viral", "input": {"prompt": "x"}},
    )
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNSUPPORTED_TEMPLATE"


def test_template_missing_prompt(server_client):
    client, _ = server_client
    res = client.post(
        "/api/generation/template",
        json={"template_id": "avatar-viral", "input": {"prompt": "  "}},
    )
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_template_provider_error_sanitized(server_client, monkeypatch):
    client, _ = server_client
    import core.integrations.image_generation as image_generation

    def fail(prompt, **kw):
        raise image_generation.ImageGenerationError(
            image_generation.ERR_PROVIDER_FAILED, "safe failure"
        )

    monkeypatch.setattr(image_generation, "generate_image", fail)
    res = client.post(
        "/api/generation/template",
        json={"template_id": "avatar-viral", "input": {"prompt": "x"}},
    )
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == image_generation.ERR_PROVIDER_FAILED
    assert body["error"]["retryable"] is True
    # 不泄露 provider 内部细节之外的内容已由 image_generation 层保证


def test_template_unexpected_error_sanitized(server_client, monkeypatch):
    client, _ = server_client
    import core.integrations.image_generation as image_generation

    def boom(prompt, **kw):
        raise RuntimeError("internal detail should not leak")

    monkeypatch.setattr(image_generation, "generate_image", boom)
    res = client.post(
        "/api/generation/template",
        json={"template_id": "avatar-viral", "input": {"prompt": "x"}},
    )
    body = res.json()
    assert body["ok"] is False
    assert "internal detail" not in body["error"]["message"]


def test_template_does_not_break_image_endpoint(server_client, monkeypatch):
    """回归：/api/generation/image 仍可用。"""
    client, _ = server_client
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    res = client.post("/api/generation/image", json={"template_id": "ai-image", "prompt": "猫"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
