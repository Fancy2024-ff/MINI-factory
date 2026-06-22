"""core.integrations.image_generation 回归测试。

覆盖：缺 endpoint / 缺 key / timeout / provider 失败 / 非法响应 / 成功归一化 /
错误与日志不泄露 key / provider 敏感字段不透传。网络请求全程 mock，不依赖真实中转站。
"""

import httpx
import pytest

from core.integrations import image_generation as ig


@pytest.fixture
def configured(monkeypatch):
    """配置好 endpoint + key（模块级常量），供成功/失败路径测试。"""
    monkeypatch.setattr(ig, "IMAGE_GENERATION_ENDPOINT", "https://relay.example/api/img")
    monkeypatch.setattr(ig, "IMAGE_GENERATION_API_KEY", "test-secret-key-DO-NOT-LEAK")
    monkeypatch.setattr(ig, "IMAGE_GENERATION_PROVIDER", "nano-banana")
    monkeypatch.setattr(ig, "IMAGE_GENERATION_TIMEOUT_SECONDS", 5)


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_missing_endpoint(monkeypatch):
    monkeypatch.setattr(ig, "IMAGE_GENERATION_ENDPOINT", "")
    monkeypatch.setattr(ig, "IMAGE_GENERATION_API_KEY", "k")
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_NOT_CONFIGURED


def test_missing_api_key(monkeypatch):
    monkeypatch.setattr(ig, "IMAGE_GENERATION_ENDPOINT", "https://relay.example")
    monkeypatch.setattr(ig, "IMAGE_GENERATION_API_KEY", "")
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_NOT_CONFIGURED


def test_empty_prompt(configured):
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("   ")
    assert e.value.code == ig.ERR_FAILED


def test_timeout(configured, monkeypatch):
    def _raise(*a, **k):
        raise httpx.TimeoutException("timeout")
    monkeypatch.setattr(ig.httpx, "post", _raise)
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_TIMEOUT


def test_auth_failed(configured, monkeypatch):
    monkeypatch.setattr(ig.httpx, "post", lambda *a, **k: _Resp(401, {}))
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_AUTH_FAILED


def test_provider_failed_status(configured, monkeypatch):
    monkeypatch.setattr(ig.httpx, "post", lambda *a, **k: _Resp(500, {}))
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_PROVIDER_FAILED


def test_provider_http_error(configured, monkeypatch):
    def _raise(*a, **k):
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(ig.httpx, "post", _raise)
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_PROVIDER_FAILED


def test_malformed_json(configured, monkeypatch):
    monkeypatch.setattr(ig.httpx, "post", lambda *a, **k: _Resp(200, ValueError("not json")))
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_MALFORMED_RESPONSE


def test_malformed_no_image(configured, monkeypatch):
    monkeypatch.setattr(ig.httpx, "post", lambda *a, **k: _Resp(200, {"foo": "bar"}))
    with pytest.raises(ig.ImageGenerationError) as e:
        ig.generate_image("a cat")
    assert e.value.code == ig.ERR_MALFORMED_RESPONSE


def test_success_normalizes(configured, monkeypatch):
    monkeypatch.setattr(
        ig.httpx, "post",
        lambda *a, **k: _Resp(200, {"image_url": "https://img/x.png", "metadata": {"w": 512}}),
    )
    out = ig.generate_image("a cat", style="oil", aspect_ratio="1:1")
    assert out["status"] == "succeeded"
    assert out["provider"] == "nano-banana"
    assert out["image_url"] == "https://img/x.png"
    assert out["image_base64"] is None
    assert out["prompt"] == "a cat"
    assert out["metadata"] == {"w": 512}


def test_success_nested_data(configured, monkeypatch):
    monkeypatch.setattr(
        ig.httpx, "post",
        lambda *a, **k: _Resp(200, {"data": [{"url": "https://img/y.png"}]}),
    )
    out = ig.generate_image("a dog")
    assert out["image_url"] == "https://img/y.png"


def test_sensitive_fields_stripped(configured, monkeypatch):
    """provider 响应里的 key/token 不能透传到统一结构（metadata 或任何字段）。"""
    monkeypatch.setattr(
        ig.httpx, "post",
        lambda *a, **k: _Resp(200, {
            "image_url": "https://img/z.png",
            "api_key": "LEAK-KEY",
            "token": "LEAK-TOKEN",
            "metadata": {"secret": "LEAK", "w": 256},
        }),
    )
    out = ig.generate_image("a bird")
    flat = str(out)
    assert "LEAK-KEY" not in flat
    assert "LEAK-TOKEN" not in flat
    assert "LEAK" not in flat
    assert out["metadata"].get("w") == 256


def test_error_message_has_no_key(configured, monkeypatch):
    """鉴权失败等异常的 message 不含真实 key。"""
    monkeypatch.setattr(ig.httpx, "post", lambda *a, **k: _Resp(403, {}))
    try:
        ig.generate_image("a cat")
    except ig.ImageGenerationError as e:
        assert "test-secret-key-DO-NOT-LEAK" not in str(e)
        assert "test-secret-key-DO-NOT-LEAK" not in e.message
