"""已上架功能页清单（deployed_apps）测试。"""

from __future__ import annotations

import json

from core.publisher.deployed_apps import (
    BUILTIN_FEATURES,
    list_deployed_features,
)


def _write_telegram(tmp_path, url="https://miniforge-app.pages.dev"):
    p = tmp_path / "telegram.json"
    p.write_text(json.dumps({"webapp_url": url}), encoding="utf-8")
    return p


def test_returns_empty_when_not_deployed(tmp_path):
    # 无 telegram.json → 视为未上架
    out = list_deployed_features(tmp_path / "telegram.json", tmp_path / "features.generated.json")
    assert out == []


def test_lists_builtin_features_when_deployed(tmp_path):
    tg = _write_telegram(tmp_path)
    out = list_deployed_features(tg, tmp_path / "features.generated.json")
    routes = {f["route"] for f in out}
    assert routes == {f["route"] for f in BUILTIN_FEATURES}
    # 每条带 preview_url = webapp_url + route
    avatar = next(f for f in out if f["route"] == "/tg/avatar")
    assert avatar["preview_url"] == "https://miniforge-app.pages.dev/tg/avatar"


def test_merges_generated_features(tmp_path):
    tg = _write_telegram(tmp_path)
    reg = tmp_path / "features.generated.json"
    reg.write_text(json.dumps([{"id": "meme-king", "title": "梗王", "icon": "🤣"}]), encoding="utf-8")
    out = list_deployed_features(tg, reg)
    gen = next((f for f in out if f["route"] == "/tg/gen/meme-king"), None)
    assert gen is not None
    assert gen["title"] == "梗王" and gen["source"] == "generated"
    assert gen["preview_url"] == "https://miniforge-app.pages.dev/tg/gen/meme-king"


def test_generated_without_id_skipped(tmp_path):
    tg = _write_telegram(tmp_path)
    reg = tmp_path / "features.generated.json"
    reg.write_text(json.dumps([{"title": "无id"}, {"id": "ok", "title": "ok"}]), encoding="utf-8")
    out = list_deployed_features(tg, reg)
    gen_routes = [f["route"] for f in out if f["source"] == "generated"]
    assert gen_routes == ["/tg/gen/ok"]


def test_uses_deploy_url_when_webapp_url_missing(tmp_path):
    p = tmp_path / "telegram.json"
    p.write_text(json.dumps({"deploy_url": "https://x.pages.dev"}), encoding="utf-8")
    out = list_deployed_features(p, tmp_path / "features.generated.json")
    assert out and out[0]["preview_url"].startswith("https://x.pages.dev/tg/")
