"""Google Play 直爬实现测试（httpx+bs4，不打真实网络）。

只验证 HTML 解析与入口边界，不依赖任何第三方库（google-play-scraper 已移除）。
"""

from __future__ import annotations

import pytest

from core.opportunity.scrapers import googleplay as gp
from core.opportunity import crawl_config as cfg
from core.shared.models import AppSource


_SAMPLE_HTML = """
<html><body>
  <a href="/store/apps/details?id=com.example.photo" aria-label="AI Photo Editor">AI Photo Editor</a>
  <a href="/store/apps/details?id=com.example.avatar" aria-label="Avatar Maker">Avatar Maker</a>
  <a href="/store/apps/details?id=com.example.photo">dup link same package</a>
  <a href="/store/search?q=more">不是应用卡片</a>
</body></html>
"""


def test_no_third_party_library_imported():
    # 直爬实现不应导入 google_play_scraper
    import importlib
    src = importlib.import_module("core.opportunity.scrapers.googleplay")
    assert not hasattr(src, "gp_search")
    assert not hasattr(src, "gp_collection")


def test_parse_search_html_extracts_packages():
    apps = gp._parse_search_html(_SAMPLE_HTML, limit=10)
    pkgs = [a.app_id for a in apps]
    assert "com.example.photo" in pkgs
    assert "com.example.avatar" in pkgs
    # 同 package 去重
    assert pkgs.count("com.example.photo") == 1
    assert all(a.source == AppSource.GOOGLE_PLAY for a in apps)


def test_search_passes_country_and_uses_get_text(monkeypatch):
    """country 真生效：URL 含 gl=<country>，且走 fetch_policy.get_text（直爬）。"""
    captured = {}

    def fake_get_text(url, params=None):
        captured["url"] = url
        return _SAMPLE_HTML

    monkeypatch.setattr(gp.fetch_policy, "with_retry", lambda fn, **k: fn())
    monkeypatch.setattr(gp.fetch_policy, "get_text", fake_get_text)
    monkeypatch.setattr(gp.fetch_policy, "pace", lambda: None)

    apps = gp.fetch_ai_apps_googleplay(category="photo", limit=5, country="jp",
                                       entry_type=cfg.SEARCH, keywords=["AI photo"])
    assert "gl=jp" in captured["url"]
    assert "hl=ja" in captured["url"]  # jp -> ja
    assert len(apps) >= 1


def test_multi_keyword_paces_between_requests(monkeypatch):
    pace_calls = {"n": 0}
    monkeypatch.setattr(gp.fetch_policy, "with_retry", lambda fn, **k: fn())
    monkeypatch.setattr(gp.fetch_policy, "get_text", lambda url, params=None: _SAMPLE_HTML)
    monkeypatch.setattr(gp.fetch_policy, "pace", lambda: pace_calls.__setitem__("n", pace_calls["n"] + 1))
    gp.fetch_ai_apps_googleplay(category="photo", limit=30, country="us",
                                entry_type=cfg.SEARCH, keywords=["k1", "k2", "k3"])
    assert pace_calls["n"] == 2  # 3 关键词 -> 第 2、3 次请求前各 pace


def test_top_grossing_unsupported_raises():
    with pytest.raises(gp.GooglePlayUnsupportedEntry):
        gp.fetch_ai_apps_googleplay(category="photo", country="us", entry_type=cfg.TOP_GROSSING)


def test_network_failure_degrades_to_empty(monkeypatch):
    def boom():
        raise RuntimeError("blocked")
    monkeypatch.setattr(gp.fetch_policy, "with_retry", lambda fn, **k: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(gp.fetch_policy, "pace", lambda: None)
    apps = gp.fetch_ai_apps_googleplay(category="photo", country="us",
                                       entry_type=cfg.SEARCH, keywords=["k1"])
    assert apps == []  # 失败降级，不抛
