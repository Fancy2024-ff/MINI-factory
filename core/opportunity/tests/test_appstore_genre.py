"""App Store 榜单 genre 按类目真实生效测试 — 不打真实网络。"""

from __future__ import annotations

import pytest

from core.opportunity import crawl_config as cfg
from core.opportunity import crawl_runner as cr
from core.opportunity.scrapers import appstore
from core.opportunity.scrapers.appstore import appstore_rss_url, AppStoreGenreUnsupported
from core.shared.models import AppInfo, AppSource


def test_genre_map_has_core_categories():
    assert cfg.appstore_genre("photo") == "6008"
    assert cfg.appstore_genre("entertainment") == "6016"
    assert cfg.appstore_genre("utilities") == "6002"
    assert cfg.appstore_genre("education") == "6017"


def test_photo_top_free_url_contains_genre_6008():
    url = appstore_rss_url(cfg.TOP_FREE, 5, "us", "photo")
    assert "genre=6008" in url
    assert "topfreeapplications" in url


def test_entertainment_url_differs_from_photo():
    u_photo = appstore_rss_url(cfg.TOP_FREE, 5, "us", "photo")
    u_ent = appstore_rss_url(cfg.TOP_FREE, 5, "us", "entertainment")
    assert u_photo != u_ent
    assert "genre=6016" in u_ent


def test_different_categories_never_share_identical_url():
    urls = {c: appstore_rss_url(cfg.TOP_FREE, 5, "us", c)
            for c in ["photo", "entertainment", "utilities", "education"]}
    assert len(set(urls.values())) == len(urls), f"类目榜单 URL 不应重复: {urls}"


def test_unmapped_category_raises():
    with pytest.raises(AppStoreGenreUnsupported):
        appstore_rss_url(cfg.TOP_FREE, 5, "us", "no-such-category")


def test_top_grossing_also_uses_genre():
    url = appstore_rss_url(cfg.TOP_GROSSING, 5, "us", "photo")
    assert "topgrossingapplications" in url and "genre=6008" in url


def test_crawl_report_records_genre_for_ranking_tasks():
    def fake_as(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        return [AppInfo(name="X", app_id=f"as-{country}-{category}-{entry_type}",
                        source=AppSource.APP_STORE, category=category, description="AI photo retouch")]

    rep = cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo", "entertainment"],
        entry_types=[cfg.TOP_FREE], dry_run=True,
        appstore_fetch=fake_as, googleplay_fetch=lambda **kw: [],
    )
    ranking_tasks = [t for t in rep["tasks"] if t.get("rank_kind") == "ranking"]
    assert ranking_tasks, "应有榜单任务"
    photo = next(t for t in ranking_tasks if t["category"] == "photo")
    ent = next(t for t in ranking_tasks if t["category"] == "entertainment")
    assert photo["actual_genre_id"] == "6008"
    assert ent["actual_genre_id"] == "6016"
    assert photo["requested_category"] == "photo"
    # capability 也暴露映射
    assert rep["data_source_capability"]["app_store"]["category_genre_map"]["photo"] == "6008"


def test_unmapped_category_ranking_task_skipped():
    def fake_as(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        return [AppInfo(name="X", app_id="x", source=AppSource.APP_STORE, category=category, description="")]

    rep = cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["mystery"],
        entry_types=[cfg.TOP_FREE], dry_run=True,
        appstore_fetch=fake_as, googleplay_fetch=lambda **kw: [],
    )
    tasks = [t for t in rep["tasks"] if t["category"] == "mystery"]
    assert tasks and tasks[0]["status"] == "skipped"
    assert "genre" in tasks[0]["reason"]


def test_appstore_rss_fetch_uses_genre_url(monkeypatch):
    """_fetch_via_rss 真实用带 genre 的 URL 请求（mock get_json 捕获 URL）。"""
    captured = {}

    def fake_get_json(url, params=None):
        captured["url"] = url
        return {"feed": {"entry": []}}

    monkeypatch.setattr(appstore.fetch_policy, "get_json", fake_get_json)
    monkeypatch.setattr(appstore.fetch_policy, "with_retry", lambda fn, **kw: fn())
    appstore._fetch_via_rss(cfg.TOP_FREE, 5, "cn", "photo")
    assert "genre=6008" in captured["url"]
    assert "/cn/" in captured["url"]
