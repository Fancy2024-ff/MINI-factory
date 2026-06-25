"""提交中心：已上架功能页 + 广告闸门配置接口测试。"""

from __future__ import annotations

import json


def _setup_paths(api, tmp_path, *, deployed=True, generated=None):
    """把广告/registry/telegram 路径重定向到隔离目录。"""
    auth = api.PLATFORM_AUTH_DIR  # conftest 已指向 tmp
    api.AD_CONFIG_PATH = auth / "ad-config.json"
    api.TELEGRAM_AUTH_PATH = auth / "telegram.json"
    reg = tmp_path / "features.generated.json"
    api.FEATURES_REGISTRY_PATH = reg
    if deployed:
        (api.TELEGRAM_AUTH_PATH).write_text(
            json.dumps({"webapp_url": "https://miniforge-app.pages.dev"}), encoding="utf-8")
    reg.write_text(json.dumps(generated or []), encoding="utf-8")


# ---- public 读接口 /api/tg/ad-config ----

def test_tg_ad_config_public_no_auth_needed(server_client, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.get("/api/tg/ad-config?route=/tg/avatar")  # 不带 X-API-Key
    assert res.status_code == 200
    assert res.json()["ad"] == {"ad_enabled": True, "ad_seconds": 30}


def test_tg_ad_config_unknown_route_uses_default(server_client, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.get("/api/tg/ad-config?route=/tg/whatever")
    assert res.json()["ad"]["ad_seconds"] == 30


# ---- 写接口 /api/submit/ad-config（需鉴权） ----

def test_update_ad_config_requires_key(server_client, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.post("/api/submit/ad-config", json={"route": "/tg/avatar", "ad_enabled": False})
    assert res.status_code == 401


def test_update_then_read_back(server_client, auth_headers, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.post("/api/submit/ad-config", headers=auth_headers,
                      json={"route": "/tg/sticker", "ad_enabled": False, "ad_seconds": 15})
    assert res.status_code == 200 and res.json()["ad"] == {"ad_enabled": False, "ad_seconds": 15}
    # public 读接口能读到刚写的值
    got = client.get("/api/tg/ad-config?route=/tg/sticker").json()
    assert got["ad"] == {"ad_enabled": False, "ad_seconds": 15}


def test_update_clamps_seconds(server_client, auth_headers, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.post("/api/submit/ad-config", headers=auth_headers,
                      json={"route": "/tg/avatar", "ad_seconds": 9999})
    assert res.json()["ad"]["ad_seconds"] == 120


def test_update_no_fields_is_noop(server_client, auth_headers, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.post("/api/submit/ad-config", headers=auth_headers, json={"route": "/tg/avatar"})
    assert res.json()["ok"] is False


# ---- 已部署列表 /api/submit/deployed-apps ----

def test_deployed_apps_lists_builtins_with_ad(server_client, auth_headers, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    res = client.get("/api/submit/deployed-apps", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 5
    avatar = next(i for i in data["items"] if i["route"] == "/tg/avatar")
    assert avatar["preview_url"].endswith("/tg/avatar")
    assert avatar["ad"] == {"ad_enabled": True, "ad_seconds": 30}


def test_deployed_apps_empty_when_not_deployed(server_client, auth_headers, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path, deployed=False)
    res = client.get("/api/submit/deployed-apps", headers=auth_headers)
    assert res.json()["total"] == 0


def test_deployed_apps_reflects_ad_override(server_client, auth_headers, tmp_path):
    client, api = server_client
    _setup_paths(api, tmp_path)
    client.post("/api/submit/ad-config", headers=auth_headers,
                json={"route": "/tg/avatar", "ad_enabled": False, "ad_seconds": 5})
    res = client.get("/api/submit/deployed-apps", headers=auth_headers)
    avatar = next(i for i in res.json()["items"] if i["route"] == "/tg/avatar")
    assert avatar["ad"] == {"ad_enabled": False, "ad_seconds": 5}
