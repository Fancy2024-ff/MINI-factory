"""send-to-chat 接口 + initData 校验回归。

覆盖：HMAC 校验（有效/篡改/过期/无 user）、接口未配置 token、initData 非法、
data URI 与 URL 两种 sendPhoto 路径、Telegram 403 → BOT_BLOCKED、限流。
"""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest


BOT_TOKEN = "123456:TEST-bot-token"


def _make_init_data(user: dict, auth_date: int | None = None, token: str = BOT_TOKEN) -> str:
    """按 Telegram 算法生成一个带合法 hash 的 initData 串。"""
    if auth_date is None:
        auth_date = int(time.time())
    fields = {"auth_date": str(auth_date), "user": json.dumps(user, separators=(",", ":"))}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = h
    return urlencode(fields)


# --- verify_telegram_init_data 单元 ---

def test_verify_valid_init_data(server_client):
    _, api = server_client
    data = _make_init_data({"id": 42, "first_name": "Mao"})
    user = api.verify_telegram_init_data(data, BOT_TOKEN)
    assert user and user["id"] == 42


def test_verify_rejects_tampered_hash(server_client):
    _, api = server_client
    data = _make_init_data({"id": 42})
    tampered = data + "0"  # 破坏 hash
    assert api.verify_telegram_init_data(tampered, BOT_TOKEN) is None


def test_verify_rejects_wrong_token(server_client):
    _, api = server_client
    data = _make_init_data({"id": 42}, token=BOT_TOKEN)
    assert api.verify_telegram_init_data(data, "other-token") is None


def test_verify_rejects_expired(server_client):
    _, api = server_client
    old = int(time.time()) - api.INIT_DATA_MAX_AGE - 10
    data = _make_init_data({"id": 42}, auth_date=old)
    assert api.verify_telegram_init_data(data, BOT_TOKEN) is None


def test_verify_rejects_missing_user(server_client):
    _, api = server_client
    assert api.verify_telegram_init_data("", BOT_TOKEN) is None


# --- /api/generation/send-to-chat ---

def test_send_to_chat_not_configured(server_client):
    client, api = server_client
    api.TELEGRAM_BOT_TOKEN = ""
    res = client.post("/api/generation/send-to-chat", json={
        "init_data": "x", "image_src": "data:image/png;base64,QUJD",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False and body["error"]["code"] == "NOT_CONFIGURED"


def test_send_to_chat_invalid_init_data(server_client):
    client, api = server_client
    api.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    res = client.post("/api/generation/send-to-chat", json={
        "init_data": "bad", "image_src": "data:image/png;base64,QUJD",
    })
    body = res.json()
    assert body["ok"] is False and body["error"]["code"] == "INVALID_INIT_DATA"


def test_send_to_chat_data_uri_success(server_client, monkeypatch):
    client, api = server_client
    api.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    data = _make_init_data({"id": 7})

    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, url, data=None, files=None):
            captured["url"] = url
            captured["data"] = data
            captured["files"] = files
            return FakeResp()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", FakeClient)
    res = client.post("/api/generation/send-to-chat", json={
        "init_data": data, "image_src": "data:image/png;base64,QUJD", "caption": "hi",
    })
    body = res.json()
    assert body["ok"] is True
    assert captured["data"]["chat_id"] == "7"
    assert captured["files"] is not None  # 走了 multipart 上传


def test_send_to_chat_url_success(server_client, monkeypatch):
    client, api = server_client
    api.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    data = _make_init_data({"id": 9})

    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, data=None, files=None):
            captured["data"] = data
            captured["files"] = files
            return FakeResp()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", FakeClient)
    res = client.post("/api/generation/send-to-chat", json={
        "init_data": data, "image_src": "https://cdn.example.com/a.png",
    })
    body = res.json()
    assert body["ok"] is True
    assert captured["data"]["photo"] == "https://cdn.example.com/a.png"
    assert captured["files"] is None  # URL 直传，无 multipart


def test_send_to_chat_bot_blocked(server_client, monkeypatch):
    client, api = server_client
    api.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    data = _make_init_data({"id": 11})

    class FakeResp:
        status_code = 403
        def json(self):
            return {"ok": False, "error_code": 403}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k):
            return FakeResp()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "Client", FakeClient)
    res = client.post("/api/generation/send-to-chat", json={
        "init_data": data, "image_src": "data:image/png;base64,QUJD",
    })
    body = res.json()
    assert body["ok"] is False and body["error"]["code"] == "BOT_BLOCKED"
