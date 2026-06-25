"""广告闸门配置（ad_config）测试。"""

from __future__ import annotations

import json

from core.publisher.ad_config import (
    HARD_DEFAULT,
    load_ad_config,
    resolve_ad,
    set_ad,
    save_ad_config,
)


def test_resolve_uses_route_record_first():
    cfg = {"_default": {"ad_enabled": True, "ad_seconds": 30},
           "/tg/sticker": {"ad_enabled": False, "ad_seconds": 15}}
    assert resolve_ad(cfg, "/tg/sticker") == {"ad_enabled": False, "ad_seconds": 15}


def test_resolve_falls_back_to_default():
    cfg = {"_default": {"ad_enabled": False, "ad_seconds": 10}}
    assert resolve_ad(cfg, "/tg/unknown") == {"ad_enabled": False, "ad_seconds": 10}


def test_resolve_falls_back_to_hard_default_when_empty():
    assert resolve_ad({}, "/tg/x") == HARD_DEFAULT


def test_resolve_route_partial_record_merges_default():
    # route 只覆盖了 enabled，seconds 应继承 _default
    cfg = {"_default": {"ad_enabled": True, "ad_seconds": 20},
           "/tg/avatar": {"ad_enabled": False}}
    assert resolve_ad(cfg, "/tg/avatar") == {"ad_enabled": False, "ad_seconds": 20}


def test_set_ad_updates_only_given_fields():
    cfg = set_ad({}, "/tg/avatar", enabled=False)
    assert cfg["/tg/avatar"] == {"ad_enabled": False}
    cfg = set_ad(cfg, "/tg/avatar", seconds=45)
    assert cfg["/tg/avatar"] == {"ad_enabled": False, "ad_seconds": 45}


def test_set_ad_clamps_seconds():
    assert set_ad({}, "/tg/x", seconds=999)["/tg/x"]["ad_seconds"] == 120
    assert set_ad({}, "/tg/x", seconds=-5)["/tg/x"]["ad_seconds"] == 0


def test_set_ad_coerces_enabled_to_bool():
    assert set_ad({}, "/tg/x", enabled=1)["/tg/x"]["ad_enabled"] is True
    assert set_ad({}, "/tg/x", enabled=0)["/tg/x"]["ad_enabled"] is False


def test_load_missing_file_returns_default(tmp_path):
    cfg = load_ad_config(tmp_path / "nope.json")
    assert cfg == {"_default": dict(HARD_DEFAULT)}


def test_load_corrupt_file_returns_default(tmp_path):
    p = tmp_path / "ad-config.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_ad_config(p) == {"_default": dict(HARD_DEFAULT)}


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "ad-config.json"
    cfg = set_ad({"_default": dict(HARD_DEFAULT)}, "/tg/sticker", enabled=False, seconds=15)
    save_ad_config(p, cfg)
    loaded = load_ad_config(p)
    assert loaded["/tg/sticker"] == {"ad_enabled": False, "ad_seconds": 15}
    assert resolve_ad(loaded, "/tg/sticker") == {"ad_enabled": False, "ad_seconds": 15}


def test_load_injects_default_if_absent(tmp_path):
    p = tmp_path / "ad-config.json"
    p.write_text(json.dumps({"/tg/avatar": {"ad_enabled": False, "ad_seconds": 5}}), encoding="utf-8")
    loaded = load_ad_config(p)
    assert "_default" in loaded
