"""抓取 runner 测试 — mock scraper，不打真实网络。"""

from __future__ import annotations

from core.opportunity import crawl_runner as cr
from core.opportunity import crawl_config as cfg
from core.shared.models import AppInfo, AppSource


def _fake_appstore(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
    # app_id 含 country+entry_type，确保不同地区/入口数据不同（防“全地区同数据”回归）
    return [
        AppInfo(
            name="CapCut", app_id=f"as-{country}-{entry_type}", source=AppSource.APP_STORE,
            category="Photo & Video",
            description="AI photo retouch, background remover, photo enhancer, AI subtitles for long video",
            downloads=5_000_000, rating=4.8, features=["AI 修图"],
        )
    ]


def _fake_gp(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
    return [
        AppInfo(
            name="Picsart", app_id=f"gp-{country}-{entry_type}", source=AppSource.GOOGLE_PLAY,
            category="photo", description="photo enhancer and sticker maker",
            downloads=9_000_000, rating=4.6,
        )
    ]


# --- A1: run_once 防御字符串入参（worker crawl 路径回归） -------------------

def test_run_once_accepts_string_platforms_regions():
    """worker 传字符串 'app_store' 不应被按字符遍历成 0 任务。"""
    calls = []

    def fake_appstore(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        calls.append(country)
        return [AppInfo(name="X", app_id=f"as-{country}", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch background remover")]

    rep = cr.run_once(
        regions="US", platforms="app_store", categories="photo", entry_types="search",
        limit=5, dry_run=True,
        appstore_fetch=fake_appstore, googleplay_fetch=lambda **k: [],
    )
    # 字符串被正确拆成 list → 至少发起了一次真实任务（不是 0）
    assert rep["summary"]["tasks"] >= 1
    assert len(calls) >= 1


def test_run_once_accepts_csv_string_multi_values():
    """逗号分隔字符串 'CN,US' 应被拆成多地区，而非按字符遍历。"""
    seen = []

    def fake_appstore(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        seen.append(country)
        return [AppInfo(name="X", app_id=f"as-{country}", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch")]

    cr.run_once(
        regions="CN,US", platforms="app_store", categories="photo", entry_types="search",
        dry_run=True, appstore_fetch=fake_appstore, googleplay_fetch=lambda **k: [],
    )
    assert "cn" in seen and "us" in seen, f"应按逗号拆成 CN/US，实际: {seen}"


def test_run_once_still_accepts_list():
    """list 入参保持原有行为。"""
    def fake_appstore(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        return [AppInfo(name="Y", app_id=f"as-{country}", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch background remover")]

    rep = cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo"], entry_types=["search"],
        limit=5, dry_run=True,
        appstore_fetch=fake_appstore, googleplay_fetch=lambda **k: [],
    )
    assert rep["summary"]["tasks"] >= 1


def test_cn_appstore_supported_in_config():
    assert cfg.REGION_SUPPORT["CN"]["app_store"] == cfg.SUPPORTED
    assert "CN" in cfg.DEFAULT_APP_STORE_REGIONS


def test_google_play_cn_unsupported_in_config():
    assert cfg.REGION_SUPPORT["CN"]["google_play"] == cfg.UNSUPPORTED
    assert "CN" not in cfg.DEFAULT_GOOGLE_PLAY_REGIONS


def test_dry_run_produces_candidate_queue_report():
    rep = cr.run_once(
        regions=["CN", "US"], platforms=["app_store", "google_play"], categories=["photo"],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    assert rep["dry_run"] is True
    assert rep["counts"]["candidates"] >= 1
    assert rep["counts"]["queue_pending"] >= 1
    # 富报告字段（P1-7）
    assert "crawl_stats" in rep and "dedup_stats" in rep
    assert "feature_stats" in rep and "queue_stats" in rep
    assert "data_source_capability" in rep


def test_crawl_report_has_brief_stats_and_counts():
    """crawl_runner 生成机会简报：brief_stats + counts.briefs_* 存在且自洽。"""
    rep = cr.run_once(
        regions=["CN", "US"], platforms=["app_store"], categories=["photo"],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    bs = rep.get("brief_stats")
    assert bs is not None
    for k in ("total", "produce", "review", "skip", "avg_confidence"):
        assert k in bs
    assert bs["total"] == bs["produce"] + bs["review"] + bs["skip"]
    c = rep["counts"]
    assert "briefs_total" in c and "briefs_produce" in c and "briefs_review" in c
    assert "briefs_skip" in c
    assert c["briefs_total"] == c["briefs_produce"] + c["briefs_review"] + c["briefs_skip"]
    # 队列只接收 produce/review，pending 不超过 produce+review
    assert c["queue_pending"] <= bs["produce"] + bs["review"]


def test_google_play_cn_task_is_skipped_with_reason():
    rep = cr.run_once(
        regions=["CN"], platforms=["google_play"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    gp_cn = [t for t in rep["tasks"] if t["platform"] == "google_play" and t["region"] == "CN"]
    assert gp_cn and gp_cn[0]["status"] == "skipped"
    assert "Google Play" in gp_cn[0]["reason"]


def test_appstore_cn_task_runs():
    rep = cr.run_once(
        regions=["CN"], platforms=["app_store"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    as_cn = [t for t in rep["tasks"] if t["platform"] == "app_store" and t["region"] == "CN"]
    assert as_cn and as_cn[0]["status"] == "success"


def test_scraper_failure_degrades_not_crash(monkeypatch):
    def boom(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        raise RuntimeError("network blocked")

    monkeypatch.setitem(cr.cfg.CRAWL_PARAMS, "retry_base_delay", 0)
    rep = cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=boom, googleplay_fetch=_fake_gp,
    )
    failed = [t for t in rep["tasks"] if t["status"] == "failed"]
    assert failed and "error" in failed[0]
    assert failed[0]["attempts"] == cfg.CRAWL_PARAMS["max_retries"]  # 重试后失败
    assert "counts" in rep  # 整轮未中断


# --- P0-1: Google Play 多地区真实生效 ---------------------------------------

def test_google_play_passes_distinct_country_per_region():
    seen = []

    def gp_record_country(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        seen.append(country)
        return [AppInfo(name="X", app_id=f"gp-{country}", source=AppSource.GOOGLE_PLAY,
                        category="photo", description="photo enhancer")]

    cr.run_once(
        regions=["US", "JP"], platforms=["google_play"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=gp_record_country,
    )
    assert "us" in seen and "jp" in seen, f"GP 各地区应传不同 country，实际: {seen}"


def test_different_regions_yield_different_app_ids():
    rep = cr.run_once(
        regions=["US", "JP"], platforms=["google_play"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    # _fake_gp 的 app_id 含 country，US/JP 应产生不同候选（不再全地区同一 App）
    assert rep["counts"]["candidates"] >= 2


# --- P0-2: 榜单 vs 搜索入口 -------------------------------------------------

def test_appstore_search_record_entry_type():
    rep = cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    as_tasks = [t for t in rep["tasks"] if t["platform"] == "app_store"]
    assert all(t["entry_type"] == cfg.SEARCH for t in as_tasks)


def test_appstore_top_free_entry_type_supported():
    # mock 注入：top_free 入口真实跑通并记 entry_type=top_free
    seen_entry = []

    def fake_as(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        seen_entry.append(entry_type)
        return [AppInfo(name="Top1", app_id=f"as-{country}-{entry_type}", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch")]

    rep = cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo"], entry_types=[cfg.TOP_FREE],
        dry_run=True, appstore_fetch=fake_as, googleplay_fetch=_fake_gp,
    )
    assert cfg.TOP_FREE in seen_entry
    as_tasks = [t for t in rep["tasks"] if t["platform"] == "app_store" and t["status"] == "success"]
    assert as_tasks and as_tasks[0]["entry_type"] == cfg.TOP_FREE


def test_google_play_top_grossing_unsupported_skipped():
    rep = cr.run_once(
        regions=["US"], platforms=["google_play"], categories=["photo"], entry_types=[cfg.TOP_GROSSING],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    gp = [t for t in rep["tasks"] if t["platform"] == "google_play"]
    assert gp and gp[0]["status"] == "skipped"
    assert "top_grossing" in gp[0]["reason"]


# --- P0-4: 关键词单一事实源 -------------------------------------------------

def test_keywords_passed_to_scraper_and_recorded():
    captured = {}

    def fake_as(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        captured["keywords"] = keywords
        return [AppInfo(name="X", app_id="as-x", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch background remover")]

    cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo"], entry_types=[cfg.SEARCH],
        dry_run=True, appstore_fetch=fake_as, googleplay_fetch=_fake_gp,
    )
    # 关键词来自 crawl_config.CATEGORY_KEYWORDS["photo"]，非 None
    assert captured["keywords"] == cfg.keywords_for_category("photo")
    assert "background remover" in captured["keywords"]


def test_search_record_carries_real_keywords():
    rep_records = []

    def fake_as(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        return [AppInfo(name="X", app_id="as-x", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch")]

    # 用 _appinfo_to_records 直接验证记录里的 keywords 是真实关键词
    from core.shared.models import AppInfo as AI
    apps = [AI(name="X", app_id="x", source=AppSource.APP_STORE, category="photo", description="")]
    recs = cr._appinfo_to_records(apps, "app_store", "US", "photo", cfg.SEARCH,
                                  ["AI photo editor", "background remover"])
    assert "AI photo editor" in recs[0]["keywords"]
    assert recs[0]["entry_type"] == cfg.SEARCH
    assert recs[0]["rank_kind"] == "search_position"


def test_ranking_record_top_free_is_ranking_kind():
    from core.shared.models import AppInfo as AI
    apps = [AI(name="X", app_id="x", source=AppSource.APP_STORE, category="photo", description="")]
    recs = cr._appinfo_to_records(apps, "app_store", "US", "photo", cfg.TOP_FREE, [])
    assert recs[0]["entry_type"] == cfg.TOP_FREE
    assert recs[0]["rank_kind"] == "ranking"


# --- P0-3: pace 单请求级被调用 ---------------------------------------------

def test_pace_called_between_tasks(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(cr.fetch_policy, "pace", lambda: calls.__setitem__("n", calls["n"] + 1))
    cr.run_once(
        regions=["US"], platforms=["app_store"], categories=["photo"], entry_types=[cfg.SEARCH, cfg.TOP_FREE],
        dry_run=True, appstore_fetch=_fake_appstore, googleplay_fetch=_fake_gp,
    )
    assert calls["n"] >= 2  # 两个成功任务之间各 pace 一次


# --- P0: 榜单 rating 缺失不应导致 queue_pending=0 ---------------------------

def _fake_appstore_ranking_no_rating(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
    """模拟 Apple RSS 榜单：有名字/描述，但无 rating（rating=0）。"""
    return [
        AppInfo(name="TopApp", app_id=f"as-{country}-{category}", source=AppSource.APP_STORE,
                category=category, description="AI photo retouch and background remover",
                downloads=0, rating=0.0),  # 榜单无评分
    ]


def test_top_free_dry_run_queue_pending_positive():
    """复现命令场景：top_free 抓到数据 → 不被 rating 过滤清零。

    注意：自 Opportunity Brief 接入后，队列由 recommendation（produce/review）门控，
    不再由 rating 门控。本测试保证「rating 缺失不会把榜单 feature 过滤掉」的原始契约：
    features_recommended 仍 > 0（榜单 feature 进入排名与简报），queue 是否进则由
    brief 的 confidence/score 决定（thin 数据可能全 skip，属预期）。
    """
    rep = cr.run_once(
        regions=["CN", "US"], platforms=["app_store"], categories=["photo", "entertainment"],
        entry_types=[cfg.TOP_FREE], limit=5, dry_run=True,
        appstore_fetch=_fake_appstore_ranking_no_rating, googleplay_fetch=_fake_gp,
    )
    assert rep["counts"]["candidates"] > 0
    assert rep["counts"]["features_total"] > 0
    # 原始契约：rating 缺失不应把榜单 feature 过滤掉（仍进入排名 + 生成简报）
    assert rep["counts"]["features_recommended"] > 0, "榜单 feature 不应被 rating 过滤"
    assert rep["brief_stats"]["total"] > 0, "榜单 feature 应生成机会简报"
    # 队列门控改为 brief 驱动：pending == produce + review（skip 不入队）
    assert rep["counts"]["queue_pending"] == (
        rep["brief_stats"]["produce"] + rep["brief_stats"]["review"]
    )


def test_candidate_pool_tracks_rating_available():
    """榜单无评分 → rating_available=False；search 有评分 → True。"""
    from core.opportunity.candidate_pool import build_candidate_pool
    recs = [
        {"source": "app_store", "app_id": "1", "name": "NoRate", "rating": 0, "entry_type": "top_free"},
        {"source": "app_store", "app_id": "2", "name": "HasRate", "rating": 4.5, "entry_type": "search"},
    ]
    pool = build_candidate_pool(recs)
    by_id = {c["canonical_key"]: c for c in pool}
    assert by_id["app_store:1"]["rating_available"] is False
    assert by_id["app_store:2"]["rating_available"] is True


# --- A2: force_refresh 绕过当日快照缓存 -------------------------------------

def test_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    """force_refresh=True 时即使有当日快照也重新抓取；默认仍命中缓存。"""
    calls = {"n": 0}

    def fake_appstore(category, limit, country, entry_type=cfg.SEARCH, keywords=None):
        calls["n"] += 1
        return [AppInfo(name="X", app_id=f"as-{country}-{entry_type}", source=AppSource.APP_STORE,
                        category="photo", description="AI photo retouch background remover")]

    # 快照 + 写盘产物都指到 tmp，避免污染真实 data/。
    monkeypatch.setattr(cr, "SNAP_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(cr, "OPP_DIR", tmp_path / "opp")
    monkeypatch.setattr(cr, "PROCESSED_PATH", tmp_path / "opp" / "processed-apps.json")

    common = dict(regions="US", platforms="app_store", categories="photo",
                  entry_types="search", limit=3,
                  appstore_fetch=fake_appstore, googleplay_fetch=lambda **k: [])

    # 第一次：真抓 + 写快照（非 dry_run）。
    cr.run_once(**common)
    after_first = calls["n"]
    assert after_first >= 1, "第一次应真实抓取"

    # 第二次默认（用缓存）：命中当日快照，不应再抓。
    cr.run_once(**common)
    assert calls["n"] == after_first, "默认应命中缓存不重抓"

    # 第三次 force_refresh=True：绕过缓存重抓。
    cr.run_once(**common, force_refresh=True)
    assert calls["n"] > after_first, "force_refresh 应绕过缓存重抓"

