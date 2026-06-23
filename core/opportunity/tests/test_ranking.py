"""ranking 评分测试 — entry_type 加权、score_breakdown、过滤。"""

from __future__ import annotations

from core.opportunity.ranking import score_feature, rank_features, _market_presence


def _feature(**kw):
    base = {
        "feature_key": "app_store:1:ai_photo_retouch",
        "parent_app_key": "app_store:1",
        "parent_app_name": "CapCut",
        "feature_name": "AI photo retouch",
        "feature_name_cn": "AI 修图",
        "miniapp_fit_score": 86,
        "implementation_score": 75,
        "viral_score": 78,
        "selected_template": "ai-image",
        "production_recommended": True,
        "reason": ["功能轻量"],
    }
    base.update(kw)
    return base


def _cand(**kw):
    base = {
        "canonical_key": "app_store:1", "name": "CapCut", "name_cn": "剪映",
        "description": "AI photo retouch",
        "regions": ["US", "CN"], "appear_count": 2, "rating": 4.8, "rating_available": True,
        "downloads": 5_000_000,
        "review_count": 100000, "entry_types": ["search"], "features": [], "best_rank": 5,
    }
    base.update(kw)
    return base


def test_top_free_market_presence_higher_than_search():
    search_cand = _cand(entry_types=["search"])
    top_cand = _cand(entry_types=["top_free"])
    assert _market_presence(top_cand) > _market_presence(search_cand)


def test_score_feature_has_breakdown_and_reason():
    out = score_feature(_feature(), _cand())
    assert "final_score" in out
    bd = out["score_breakdown"]
    for k in ["parent_app_demand", "market_presence", "miniapp_fit", "viral", "implementation", "risk"]:
        assert k in bd
    assert isinstance(out["reason"], list) and out["reason"]


def test_top_free_feature_outranks_same_search_feature():
    f = _feature()
    top = score_feature(f, _cand(entry_types=["top_free"]))
    search = score_feature(f, _cand(entry_types=["search"]))
    assert top["final_score"] > search["final_score"]


def test_rank_filters_unsupported_and_low_rating():
    feats = [_feature(), _feature(feature_key="k2", production_recommended=False)]
    by_key = {"app_store:1": _cand()}
    ranked = rank_features(feats, by_key, min_rating=3.8)
    keys = {f["feature_key"] for f in ranked}
    assert "app_store:1:ai_photo_retouch" in keys
    assert "k2" not in keys  # 不推荐项被过滤

    # 父 App 评分低于阈值（且评分可用、来自 search）→ 跳过
    low = _cand(rating=2.0, rating_available=True, entry_types=["search"])
    ranked2 = rank_features([_feature()], {"app_store:1": low}, min_rating=3.8)
    assert ranked2 == []


# --- P0: 榜单 rating 缺失不应被过滤 ----------------------------------------

def test_top_free_rating_missing_not_filtered():
    """top_free 候选 rating=0/缺失 仍进入 ranked（榜单即热度）。"""
    cand = _cand(rating=0.0, rating_available=False, entry_types=["top_free"], best_rank=2)
    ranked = rank_features([_feature()], {"app_store:1": cand}, min_rating=3.8)
    assert len(ranked) == 1
    # reason 说明用榜单排名作为需求信号
    assert any("榜单" in r for r in ranked[0]["reason"])


def test_search_rating_zero_available_is_filtered():
    """search 候选 rating=0 且评分可用 → 被 min_rating 过滤。"""
    cand = _cand(rating=0.0, rating_available=True, entry_types=["search"])
    ranked = rank_features([_feature()], {"app_store:1": cand}, min_rating=3.8)
    assert ranked == []


def test_search_rating_missing_not_filtered():
    """search 候选评分缺失（rating_available=False）→ 不当低质量过滤。"""
    cand = _cand(rating=0.0, rating_available=False, entry_types=["search"])
    ranked = rank_features([_feature()], {"app_store:1": cand}, min_rating=3.8)
    assert len(ranked) == 1


def test_top_free_high_rank_enters_queue():
    """top_free + 高 best_rank 的 feature 能进入 opportunity queue。"""
    from core.opportunity.opportunity_queue import build_queue
    cand = _cand(rating=0.0, rating_available=False, entry_types=["top_free"], best_rank=1)
    ranked = rank_features([_feature()], {"app_store:1": cand}, min_rating=3.8)
    queue = build_queue(ranked, processed={"features": {}}, date_str="20260623")
    assert len(queue) >= 1
    assert queue[0]["status"] == "pending"
