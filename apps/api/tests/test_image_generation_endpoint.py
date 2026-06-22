"""apps/api image generation endpoint regression tests.

权限边界：/api/generation/image 是面向生成产物（小程序前端）的 runtime/public 接口，
即便 DASHBOARD_API_KEY 已配置（server_client fixture 默认开启），也必须无需 dashboard
key 即可调用——生成出来的小程序不持有该 key。
"""

import pytest


def _fake_ok(prompt, style="", aspect_ratio="1:1"):
    return {
        "provider": "test-provider",
        "status": "succeeded",
        "image_url": "https://img.example/result.png",
        "image_base64": None,
        "prompt": prompt,
        "metadata": {"style": style, "ratio": aspect_ratio},
    }


def test_image_generation_public_no_dashboard_key(server_client, monkeypatch):
    """无 dashboard key（不带 X-API-Key）也能调用 runtime 图片生成接口。"""
    client, _ = server_client  # fixture 已设 DASHBOARD_API_KEY=secret123
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    res = client.post(
        "/api/generation/image",
        json={"template_id": "ai-image", "prompt": "cat"},  # 注意：无 headers
    )
    assert res.status_code == 200, "runtime 接口不应要求 dashboard 鉴权"
    body = res.json()
    assert body["ok"] is True
    assert body["result"]["image_url"] == "https://img.example/result.png"


def test_image_generation_success(server_client, monkeypatch):
    client, _ = server_client
    import core.integrations.image_generation as image_generation

    monkeypatch.setattr(image_generation, "generate_image", _fake_ok)
    res = client.post(
        "/api/generation/image",
        json={"template_id": "ai-image", "prompt": "cat", "style": "oil", "aspect_ratio": "1:1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["result"]["preview_type"] == "image"
    assert body["result"]["image_url"] == "https://img.example/result.png"
    assert body["result"]["prompt"] == "cat"


def test_image_generation_missing_prompt(server_client):
    client, _ = server_client
    res = client.post(
        "/api/generation/image",
        json={"template_id": "ai-image", "prompt": "   "},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_image_generation_prompt_too_long(server_client):
    client, api = server_client
    over = "x" * (api.MAX_PROMPT_LEN + 1)
    res = client.post(
        "/api/generation/image",
        json={"template_id": "ai-image", "prompt": over},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "过长" in body["error"]["message"]


def test_image_generation_rejects_unsupported_template(server_client):
    client, _ = server_client
    res = client.post(
        "/api/generation/image",
        json={"template_id": "avatar-viral", "prompt": "cat"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UNSUPPORTED_TEMPLATE"


def test_image_generation_error_is_structured(server_client, monkeypatch):
    client, _ = server_client
    import core.integrations.image_generation as image_generation

    def fail(*args, **kwargs):
        raise image_generation.ImageGenerationError(image_generation.ERR_PROVIDER_FAILED, "safe failure")

    monkeypatch.setattr(image_generation, "generate_image", fail)
    res = client.post(
        "/api/generation/image",
        json={"template_id": "ai-image", "prompt": "cat"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == image_generation.ERR_PROVIDER_FAILED
    assert "safe failure" in body["error"]["message"]


def test_image_generation_unexpected_error_is_sanitized(server_client, monkeypatch):
    client, _ = server_client
    import core.integrations.image_generation as image_generation

    def fail(*args, **kwargs):
        raise RuntimeError("internal provider detail should not leak")

    monkeypatch.setattr(image_generation, "generate_image", fail)
    res = client.post(
        "/api/generation/image",
        json={"template_id": "ai-image", "prompt": "cat"},
    )
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == image_generation.ERR_FAILED
    assert "internal provider detail" not in body["error"]["message"]


def test_dashboard_management_endpoints_still_require_auth(server_client):
    """边界回归：放开 runtime 图片接口的同时，dashboard 管理接口仍须 401（未带 key）。"""
    client, _ = server_client
    # 管理接口（写/敏感读）在配置了 DASHBOARD_API_KEY 时必须拒绝无 key 请求。
    assert client.post("/api/pipeline/start", json={"mode": "demo"}).status_code == 401
    assert client.get("/api/jobs/latest").status_code == 401
    assert client.get("/api/real-inputs/apps").status_code == 401
