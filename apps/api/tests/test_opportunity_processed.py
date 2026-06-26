"""apps/api processed-apps 查看/重置接口测试（A3）。

覆盖：GET 摘要、reset all（清空 + 备份）、reset 单条、鉴权、未知 key 404。
"""

from __future__ import annotations

import json


def _seed_processed(api, features):
    opp = api.OUTPUTS_DIR.parent / "opportunity"
    opp.mkdir(parents=True, exist_ok=True)
    api.OPPORTUNITY_DIR = opp
    (opp / "processed-apps.json").write_text(
        json.dumps({"features": features}, ensure_ascii=False), encoding="utf-8"
    )
    return opp


def _features():
    return {
        "app_store:com.a:sticker": {
            "status": "produced", "parent_app_key": "app_store:com.a",
            "job_id": "job-1", "produced_at": "2026-06-23T06:33:36+00:00",
        },
        "app_store:com.a:bg_remover": {
            "status": "produced", "parent_app_key": "app_store:com.a",
            "job_id": "job-2", "produced_at": "2026-06-23T06:38:29+00:00",
        },
    }


def test_processed_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/opportunities/processed").status_code == 401
    assert client.post("/api/opportunities/processed/reset", json={}).status_code == 401


def test_get_processed_returns_summary(server_client, auth_headers):
    client, api = server_client
    _seed_processed(api, _features())
    res = client.get("/api/opportunities/processed", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    keys = {f["feature_key"] for f in body["features"]}
    assert keys == {"app_store:com.a:sticker", "app_store:com.a:bg_remover"}
    one = next(f for f in body["features"] if f["feature_key"] == "app_store:com.a:sticker")
    assert one["parent_app_key"] == "app_store:com.a"
    assert one["status"] == "produced"
    assert one["job_id"] == "job-1"


def test_get_processed_empty_when_missing(server_client, auth_headers):
    client, api = server_client
    opp = api.OUTPUTS_DIR.parent / "opportunity"
    opp.mkdir(parents=True, exist_ok=True)
    api.OPPORTUNITY_DIR = opp
    res = client.get("/api/opportunities/processed", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"count": 0, "features": []}


def test_reset_all_clears_and_backups(server_client, auth_headers):
    client, api = server_client
    opp = _seed_processed(api, _features())
    res = client.post("/api/opportunities/processed/reset", headers=auth_headers, json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["removed"] == 2
    assert body["remaining"] == 0
    # 文件已清空
    data = json.loads((opp / "processed-apps.json").read_text(encoding="utf-8"))
    assert data["features"] == {}
    # 生成了备份且内容是重置前的
    assert body["backup"] is not None
    backups = list(opp.glob("processed-apps.backup-*.json"))
    assert len(backups) == 1
    backed = json.loads(backups[0].read_text(encoding="utf-8"))
    assert len(backed["features"]) == 2


def test_reset_all_explicit_flag(server_client, auth_headers):
    client, api = server_client
    opp = _seed_processed(api, _features())
    res = client.post("/api/opportunities/processed/reset", headers=auth_headers,
                      json={"all": True})
    assert res.status_code == 200
    assert res.json()["remaining"] == 0
    data = json.loads((opp / "processed-apps.json").read_text(encoding="utf-8"))
    assert data["features"] == {}


def test_reset_single_removes_only_one(server_client, auth_headers):
    client, api = server_client
    opp = _seed_processed(api, _features())
    res = client.post("/api/opportunities/processed/reset", headers=auth_headers,
                      json={"feature_key": "app_store:com.a:sticker"})
    assert res.status_code == 200
    body = res.json()
    assert body["removed"] == 1
    assert body["remaining"] == 1
    data = json.loads((opp / "processed-apps.json").read_text(encoding="utf-8"))
    assert "app_store:com.a:sticker" not in data["features"]
    assert "app_store:com.a:bg_remover" in data["features"]


def test_reset_single_unknown_key_404(server_client, auth_headers):
    client, api = server_client
    _seed_processed(api, _features())
    res = client.post("/api/opportunities/processed/reset", headers=auth_headers,
                      json={"feature_key": "nope"})
    assert res.status_code == 404
