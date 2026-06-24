"""Opportunity Brief 测试：生成 / 证据可追溯 / confidence / recommendation。"""

from __future__ import annotations

from core.opportunity.opportunity_brief import (
    build_brief,
    build_briefs,
    brief_stats,
    compute_confidence,
    decide_recommendation,
)
from core.opportunity.opportunity_queue import build_queue


def _feature(**kw):
    base = {
        "feature_key": "app_store:1:ai_photo_retouch",
        "parent_app_key": "app_store:1",
        "parent_app_name": "CapCut",
        "feature_name_cn": "AI 修图",
        "feature_name": "AI photo retouch",
        "selected_template": "ai-image",
        "final_score": 84.0,
        "score_breakdown": {"miniapp_fit": 86},
        "reason": ["功能轻量"],
        "required_capabilities": ["image_generation"],
        "production_recommended": True,
    }
    base.update(kw)
    return base


def _multi_region_cand(**kw):
    base = {
        "canonical_key": "app_store:1", "name": "CapCut", "name_cn": "剪映",
        "description": "AI photo retouch and background remover",
        "features": ["修图"],
        "regions": ["CN", "US"],
        "entry_types": ["top_free", "search"],
        "seen_in": ["app_store:CN:top_free", "app_store:US:search"],
        "per_region_ranks": {"CN": 2, "US": 7},
        "rating_available": True,
        "region_entries": [
            {"platform": "app_store", "region": "CN", "entry_type": "top_free",
             "rank": 2, "rank_kind": "ranking", "keywords": ["AI 修图"], "category": "photo"},
            {"platform": "app_store", "region": "US", "entry_type": "search",
             "rank": 7, "rank_kind": "search_position", "keywords": ["AI photo"], "category": "photo"},
        ],
    }
    base.update(kw)
    return base


def _single_region_cand(**kw):
    base = {
        "canonical_key": "app_store:2", "name": "Solo", "name_cn": "单区App",
        "description": "", "features": [],
        "regions": ["US"], "entry_types": ["search"],
        "seen_in": ["app_store:US:search"], "per_region_ranks": {},
        "rating_available": False,
        "region_entries": [
            {"platform": "app_store", "region": "US", "entry_type": "search",
             "rank": 30, "rank_kind": "search_position", "keywords": ["x"], "category": "ai"},
        ],
    }
    base.update(kw)
    return base


def test_build_brief_from_candidate_and_feature():
    b = build_brief(_feature(), _multi_region_cand(), seq=1, date_str="20260623")
    assert b["brief_id"] == "20260623-B001"
    assert b["feature_key"] == "app_store:1:ai_photo_retouch"
    assert b["selected_template"] == "ai-image"
    # 必备字段齐全
    for k in ("one_sentence_opportunity", "user_scenario", "mvp_scope", "evidence",
              "risk_summary", "risk_flags", "reason", "target_platforms",
              "confidence_score", "recommendation", "created_at"):
        assert k in b
    assert isinstance(b["mvp_scope"], list) and 3 <= len(b["mvp_scope"]) <= 5


def test_evidence_carries_provenance():
    b = build_brief(_feature(), _multi_region_cand(), seq=1, date_str="20260623")
    ev = b["evidence"]
    assert len(ev) == 2
    cn = next(e for e in ev if e["region"] == "CN")
    assert cn["platform"] == "app_store" and cn["entry_type"] == "top_free"
    assert cn["rank"] == 2 and "AI 修图" in cn["keywords"]


def test_confidence_multi_region_higher_than_single():
    multi = compute_confidence(_feature(), _multi_region_cand())
    single = compute_confidence(_feature(), _single_region_cand())
    assert multi > single


def test_recommendation_produce_review_skip():
    # produce: final>=75 且 confidence>=60
    assert decide_recommendation(80, 70) == "produce"
    # review: final>=65 且 confidence>=40
    assert decide_recommendation(68, 45) == "review"
    # skip: 其他
    assert decide_recommendation(50, 90) == "skip"
    assert decide_recommendation(90, 30) == "skip"


def test_build_brief_recommendation_end_to_end():
    # 多地区高分高可信 -> produce
    pb = build_brief(_feature(final_score=84.0), _multi_region_cand(), 1, "20260623")
    assert pb["recommendation"] == "produce"
    # 单地区低分低可信 -> skip
    sb = build_brief(_feature(feature_key="app_store:2:x", parent_app_key="app_store:2",
                              final_score=50.0), _single_region_cand(), 2, "20260623")
    assert sb["recommendation"] == "skip"
    assert "single_region" in sb["risk_flags"]


def test_brief_stats_aggregates():
    briefs = [
        build_brief(_feature(final_score=84.0), _multi_region_cand(), 1, "20260623"),  # produce
        build_brief(_feature(feature_key="app_store:2:x", parent_app_key="app_store:2",
                             final_score=50.0), _single_region_cand(), 2, "20260623"),  # skip
    ]
    stats = brief_stats(briefs)
    assert stats["total"] == 2
    assert stats["produce"] == 1 and stats["skip"] == 1
    assert "avg_confidence" in stats


# --- queue 集成：skip 不入队，review 带 review_required ----------------------

def test_queue_excludes_skip_and_marks_review():
    ranked = [
        _feature(feature_key="fk-produce", final_score=84.0),
        _feature(feature_key="fk-review", final_score=68.0),
        _feature(feature_key="fk-skip", final_score=50.0),
    ]
    briefs = [
        {"feature_key": "fk-produce", "recommendation": "produce", "confidence_score": 70, "brief_id": "B1"},
        {"feature_key": "fk-review", "recommendation": "review", "confidence_score": 45, "brief_id": "B2"},
        {"feature_key": "fk-skip", "recommendation": "skip", "confidence_score": 20, "brief_id": "B3"},
    ]
    queue = build_queue(ranked, processed={"features": {}}, date_str="20260623", briefs=briefs)
    keys = {q["feature_key"] for q in queue}
    assert "fk-produce" in keys and "fk-review" in keys
    assert "fk-skip" not in keys  # skip 不入队
    produce_item = next(q for q in queue if q["feature_key"] == "fk-produce")
    review_item = next(q for q in queue if q["feature_key"] == "fk-review")
    assert produce_item["review_required"] is False
    assert review_item["review_required"] is True
    assert review_item["recommendation"] == "review"
    assert review_item["brief_id"] == "B2"
    assert "confidence_score" in produce_item


def test_queue_without_briefs_backcompat():
    """不传 briefs 时行为不变（兼容旧测试/调用）。"""
    ranked = [_feature(feature_key="fk-1")]
    queue = build_queue(ranked, processed={"features": {}}, date_str="20260623")
    assert len(queue) == 1
    assert "recommendation" not in queue[0]  # 无 brief 不附加字段
