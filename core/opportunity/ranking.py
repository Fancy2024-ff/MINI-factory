"""core.opportunity.ranking — 机会排序与可解释评分。

对 FeatureOpportunity 按可配置权重打分，输出 final_score + score_breakdown + reason。
六个维度：
- parent_app_demand：父 App 需求强度（复用 demand_analysis）。
- market_presence：市场出现广度（地区数/出现次数/排名）。
- miniapp_fit：功能小程序化适配度（来自 feature_extraction）。
- viral：传播力（feature 自带，可被父 App viral 校正）。
- implementation：实现可行性（难度反向）。
- risk：风险（敏感/重功能降分）。

权重来自 scoring-config.json，缺省用 DEFAULT_WEIGHTS。
"""

from __future__ import annotations

from core.opportunity.demand_analysis import analyze_demand
from core.opportunity.viral_score import compute_viral_score

DEFAULT_WEIGHTS = {
    "parent_app_demand": 0.25,
    "market_presence": 0.20,
    "miniapp_fit": 0.20,
    "viral": 0.20,
    "implementation": 0.10,
    "risk": 0.05,
}

# 风险关键词（命中则 risk 维度降分）。
_RISK_KEYWORDS = ["medical", "医疗", "finance", "金融", "gambling", "博彩", "loan", "borrow"]


def _market_presence(candidate: dict) -> int:
    regions = len(candidate.get("regions", []) or [])
    appear = candidate.get("appear_count", 0) or 0
    best_rank = candidate.get("best_rank")
    entry_types = set(candidate.get("entry_types", []) or [])
    score = 0
    score += min(40, regions * 8)          # 地区广度（最多 5 地区满分）
    score += min(35, appear * 7)           # 出现次数
    if isinstance(best_rank, int) and best_rank > 0:
        if best_rank <= 3: score += 25
        elif best_rank <= 10: score += 18
        elif best_rank <= 50: score += 10
        else: score += 5
    # 入口加权：榜单(top_free/top_grossing)是真实热门信号，权重高于搜索。
    if "top_free" in entry_types or "top_grossing" in entry_types:
        score += 15
    elif "search" in entry_types:
        score += 5
    return min(100, score)


def _risk_score(candidate: dict, feature: dict) -> int:
    text = " ".join([
        candidate.get("description", ""),
        candidate.get("name", ""),
        feature.get("feature_name", ""),
    ]).lower()
    if any(kw in text for kw in _RISK_KEYWORDS):
        return 40
    # 重功能（不推荐）风险高
    if not feature.get("production_recommended", True):
        return 50
    return 90


def score_feature(
    feature: dict,
    candidate: dict,
    weights: dict | None = None,
) -> dict:
    """给单个 feature 打分，返回含 final_score / score_breakdown / reason 的字典。"""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    demand = analyze_demand(candidate).get("demand_score", 0)
    parent_viral = compute_viral_score(candidate).get("viral_score", 0)
    presence = _market_presence(candidate)
    fit = feature.get("miniapp_fit_score", 0)
    # feature viral 与父 App viral 取较高者的加权，避免单点偏差
    viral = round(0.6 * feature.get("viral_score", 0) + 0.4 * parent_viral, 1)
    implementation = feature.get("implementation_score", 70)
    risk = _risk_score(candidate, feature)

    breakdown = {
        "parent_app_demand": round(demand, 1),
        "market_presence": presence,
        "miniapp_fit": fit,
        "viral": viral,
        "implementation": implementation,
        "risk": risk,
    }
    final = round(sum(breakdown[k] * w[k] for k in DEFAULT_WEIGHTS), 1)

    reason = list(feature.get("reason", []))
    if presence >= 50:
        reason.append("多地区/高频出现，市场需求广")
    if demand >= 70:
        reason.append("父 App 需求强度高")
    if risk < 60:
        reason.append("含敏感或重功能，风险偏高")
    # 榜单数据通常无评分，说明用榜单排名作为需求信号（避免被误判为低质量）。
    if _is_ranking_candidate(candidate) and not candidate.get("rating_available", False):
        reason.append("榜单数据无评分，使用榜单排名作为需求信号")

    return {
        "final_score": final,
        "selected_template": feature.get("selected_template", ""),
        "score_breakdown": breakdown,
        "weights": w,
        "reason": reason,
    }


def _is_ranking_candidate(candidate: dict) -> bool:
    """候选是否来自榜单入口（top_free/top_grossing）。榜单本身即热度信号。"""
    et = set(candidate.get("entry_types", []) or [])
    return "top_free" in et or "top_grossing" in et


def rank_features(
    features: list[dict],
    candidates_by_key: dict[str, dict],
    weights: dict | None = None,
    min_rating: float = 0.0,
) -> list[dict]:
    """对 feature 列表打分并排序（仅可生产项），返回带 score 的 feature 列表。

    评分过滤规则：
    - 仅当 rating 真实可用（rating_available=True）且来自 search 入口时，才用 min_rating 过滤。
    - 榜单入口（top_free/top_grossing）即便 rating 缺失/为 0 也不过滤——榜单排名本身就是
      需求信号；评分缺失不等于低质量。
    """
    scored: list[dict] = []
    for feat in features:
        if not feat.get("production_recommended", True):
            continue
        cand = candidates_by_key.get(feat.get("parent_app_key", ""))
        if cand is None:
            continue
        if min_rating and _should_filter_by_rating(cand, min_rating):
            continue
        s = score_feature(feat, cand, weights)
        merged = {**feat, **s}
        scored.append(merged)
    scored.sort(key=lambda f: f["final_score"], reverse=True)
    return scored


def _should_filter_by_rating(candidate: dict, min_rating: float) -> bool:
    """是否应因评分过低过滤该候选。

    榜单入口 → 永不因评分过滤（榜单即热度）。
    评分缺失（rating_available=False）→ 不过滤（数据源无评分，非低质量）。
    仅「评分可用 + 非榜单 + 低于阈值」才过滤。
    """
    if _is_ranking_candidate(candidate):
        return False
    if not candidate.get("rating_available", False):
        return False
    return (candidate.get("rating", 0) or 0) < min_rating
