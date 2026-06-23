"""候选池去重合并测试。"""

from __future__ import annotations

from core.opportunity.candidate_pool import (
    build_candidate_pool,
    canonical_key,
    merge_record,
)


def _rec(**kw):
    base = {"source": "app_store", "app_id": "123", "name": "CapCut", "developer": "Bytedance"}
    base.update(kw)
    return base


def test_canonical_key_uses_source_and_id():
    assert canonical_key(_rec()) == "app_store:123"


def test_canonical_key_falls_back_to_name_developer():
    rec = {"source": "app_store", "app_id": "", "name": "Cool App", "developer": "Acme"}
    key = canonical_key(rec)
    assert key.startswith("app_store:name:")
    assert "cool app" in key


def test_same_app_multi_region_merges_into_one():
    pool: dict = {}
    merge_record(pool, _rec(region="CN", category="photo", rank=3))
    merge_record(pool, _rec(region="US", category="photo", rank=5))
    merge_record(pool, _rec(region="JP", category="entertainment", rank=2))
    assert len(pool) == 1
    cand = pool["app_store:123"]
    assert set(cand["regions"]) == {"CN", "US", "JP"}
    assert set(cand["categories"]) == {"photo", "entertainment"}
    assert cand["appear_count"] == 3
    assert cand["best_rank"] == 2  # 取最小排名


def test_different_apps_not_merged():
    pool: dict = {}
    merge_record(pool, _rec(app_id="111", name="A"))
    merge_record(pool, _rec(app_id="222", name="B"))
    assert len(pool) == 2


def test_cross_platform_same_logical_app_stay_separate_by_id():
    # 不同平台用各自 ID，canonical_key 不同（合并由后续 cross-link 处理，第一版不强并）
    pool: dict = {}
    merge_record(pool, {"source": "app_store", "app_id": "1", "name": "X"})
    merge_record(pool, {"source": "google_play", "app_id": "com.x", "name": "X"})
    assert len(pool) == 2


def test_build_pool_sorts_by_signal():
    records = [
        {"source": "app_store", "app_id": "low", "name": "Low", "rating": 3.0, "region": "US"},
        {"source": "app_store", "app_id": "hi", "name": "Hi", "rating": 4.9, "region": "US"},
        {"source": "app_store", "app_id": "hi", "name": "Hi", "rating": 4.9, "region": "CN"},
    ]
    pool = build_candidate_pool(records)
    # "Hi" 出现 2 次，排前
    assert pool[0]["name"] == "Hi"
    assert pool[0]["appear_count"] == 2


def test_keywords_and_entry_types_accumulate():
    pool: dict = {}
    merge_record(pool, _rec(region="US", keywords=["AI video"], entry_type="top_free"))
    merge_record(pool, _rec(region="US", keywords=["video editor"], entry_type="search"))
    cand = pool["app_store:123"]
    assert "AI video" in cand["keywords"] and "video editor" in cand["keywords"]
    assert set(cand["entry_types"]) == {"top_free", "search"}


def test_same_app_keeps_multiple_entry_types_across_regions():
    """同一 App 在不同地区/入口出现，合并保留所有 entry_types（榜单+搜索）。"""
    pool: dict = {}
    merge_record(pool, _rec(region="US", entry_type="top_free", keywords=["AI photo"]))
    merge_record(pool, _rec(region="JP", entry_type="search", keywords=["AI 修图"]))
    merge_record(pool, _rec(region="KR", entry_type="top_grossing", keywords=["enhance"]))
    cand = pool["app_store:123"]
    assert set(cand["entry_types"]) == {"top_free", "search", "top_grossing"}
    assert cand["appear_count"] == 3
    assert set(cand["regions"]) == {"US", "JP", "KR"}


# --- P0-3: per-region provenance（各地区原始信息可追溯）---------------------

def test_provenance_region_entries_preserved():
    pool: dict = {}
    merge_record(pool, _rec(region="CN", entry_type="top_free", category="photo",
                            keywords=["AI 修图"], rank=2))
    merge_record(pool, _rec(region="US", entry_type="search", category="photo",
                            keywords=["AI photo editor"], rank=7))
    cand = pool["app_store:123"]
    assert len(cand["region_entries"]) == 2
    cn = next(e for e in cand["region_entries"] if e["region"] == "CN")
    assert cn["entry_type"] == "top_free" and cn["rank"] == 2 and "AI 修图" in cn["keywords"]
    us = next(e for e in cand["region_entries"] if e["region"] == "US")
    assert us["rank"] == 7


def test_provenance_per_region_ranks_takes_best():
    pool: dict = {}
    merge_record(pool, _rec(region="CN", entry_type="top_free", rank=9))
    merge_record(pool, _rec(region="CN", entry_type="search", rank=3))
    merge_record(pool, _rec(region="US", entry_type="top_free", rank=5))
    cand = pool["app_store:123"]
    assert cand["per_region_ranks"]["CN"] == 3   # 取更优名次
    assert cand["per_region_ranks"]["US"] == 5


def test_provenance_seen_in_combos():
    pool: dict = {}
    merge_record(pool, _rec(region="CN", entry_type="top_free"))
    merge_record(pool, _rec(region="US", entry_type="search"))
    cand = pool["app_store:123"]
    assert "app_store:CN:top_free" in cand["seen_in"]
    assert "app_store:US:search" in cand["seen_in"]
