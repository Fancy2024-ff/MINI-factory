"""core.opportunity.opportunity_brief — 机会判断输出（Opportunity Brief）。

把 ranked features + candidate provenance 合成「可读、可追溯、可决策」的机会简报：
回答 为什么值得做 / 拆哪个功能 / 证据来自哪 / 有什么风险 / 能否进生产队列。

- confidence_score：与 final_score 正交，单独表示「这个判断有多可信」（证据充分度）。
- recommendation：produce / review / skip，由 final_score + confidence_score 共同决定。
- evidence：从 candidate provenance（region_entries / per_region_ranks / seen_in）带出
  地区、入口、名次、关键词、来源平台，确保可追溯。
"""

from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- confidence_score：证据充分度（与 final_score 正交）---------------------
def compute_confidence(feature: dict, candidate: dict) -> int:
    """根据证据充分度打 confidence_score（0-100）。规则可解释。"""
    score = 0
    regions = candidate.get("regions", []) or []
    seen_in = candidate.get("seen_in", []) or []
    per_region_ranks = candidate.get("per_region_ranks", {}) or {}
    entry_types = set(candidate.get("entry_types", []) or [])

    if len(regions) >= 2:
        score += 25                       # 多地区出现 → 需求面广，更可信
    if len(seen_in) >= 2:
        score += 20                       # 多入口/组合出现
    if per_region_ranks:
        score += 15                       # 有各地区名次
    if (candidate.get("description") or candidate.get("features")):
        score += 15                       # 有描述/功能文本，归类更靠谱
    if candidate.get("rating_available") or ("top_free" in entry_types or "top_grossing" in entry_types):
        score += 10                       # 有评分 或 来自榜单入口
    if feature.get("selected_template"):
        score += 10                       # 有明确模板落点
    if feature.get("unsupported_reasons") or feature.get("risk_flags"):
        score += 5                        # 风险/不支持已明确记录（判断更完整）
    return min(100, score)


def decide_recommendation(final_score: float, confidence_score: int) -> str:
    """produce / review / skip。final_score 不变其语义，confidence 作为可信门槛。"""
    if final_score >= 75 and confidence_score >= 60:
        return "produce"
    if final_score >= 65 and confidence_score >= 40:
        return "review"
    return "skip"


def _build_evidence(candidate: dict) -> list[dict]:
    """从 candidate provenance 带出可追溯证据列表。"""
    evidence: list[dict] = []
    for e in candidate.get("region_entries", []) or []:
        evidence.append({
            "platform": e.get("platform", ""),
            "region": e.get("region", ""),
            "entry_type": e.get("entry_type", ""),
            "rank": e.get("rank"),
            "rank_kind": e.get("rank_kind", ""),
            "keywords": e.get("keywords", []),
            "category": e.get("category", ""),
        })
    return evidence


def _risk(feature: dict, candidate: dict, confidence_score: int) -> tuple[str, list[str]]:
    """风险摘要 + 风险标签。"""
    flags: list[str] = []
    if feature.get("unsupported_reasons"):
        flags.append("capability_unsupported")
    if not candidate.get("rating_available", False) and not (
        set(candidate.get("entry_types", []) or []) & {"top_free", "top_grossing"}
    ):
        flags.append("no_rating_signal")
    if len(candidate.get("regions", []) or []) < 2:
        flags.append("single_region")
    if confidence_score < 40:
        flags.append("low_confidence")
    if not feature.get("selected_template"):
        flags.append("no_template")
    summary = "；".join({
        "capability_unsupported": "功能含暂不支持能力",
        "no_rating_signal": "缺评分/榜单信号",
        "single_region": "仅单一地区出现",
        "low_confidence": "证据不足，判断可信度低",
        "no_template": "无明确模板落点",
    }[f] for f in flags) or "暂无显著风险"
    return summary, flags


def _one_sentence(feature: dict, candidate: dict) -> str:
    name = feature.get("feature_name_cn") or feature.get("feature_name") or "该功能"
    parent = feature.get("parent_app_name") or "热门 App"
    regions = candidate.get("regions", []) or []
    region_txt = "/".join(regions[:3]) if regions else "目标市场"
    return f"从 {parent} 拆出「{name}」做轻量小程序，在 {region_txt} 已被验证有需求。"


def _user_scenario(feature: dict) -> str:
    name = feature.get("feature_name_cn") or feature.get("feature_name") or "该功能"
    return f"用户打开小程序，输入/上传素材后一键获得「{name}」结果，可分享给好友并解锁高清/去水印。"


def _mvp_scope(feature: dict) -> list[str]:
    name = feature.get("feature_name_cn") or feature.get("feature_name") or "核心功能"
    template = feature.get("selected_template") or "ai-tool"
    scope = [
        f"单一核心能力：{name}（不做多功能堆叠）",
        f"使用模板：{template}，复用既有生成/结果/分享闭环",
        "输入 → 生成 → 结果页展示 → 分享 CTA",
        "分享解锁高清/去水印（增长钩子）",
    ]
    caps = feature.get("required_capabilities") or []
    if caps:
        scope.append(f"所需能力：{', '.join(caps)}")
    return scope[:5]


def build_brief(feature: dict, candidate: dict, seq: int, date_str: str) -> dict:
    """从单个 ranked feature + 其 parent candidate 合成一条 brief。"""
    final_score = feature.get("final_score", 0)
    confidence = compute_confidence(feature, candidate)
    recommendation = decide_recommendation(final_score, confidence)
    risk_summary, risk_flags = _risk(feature, candidate, confidence)
    return {
        "brief_id": f"{date_str}-B{seq:03d}",
        "feature_key": feature.get("feature_key", ""),
        "parent_app_key": feature.get("parent_app_key", ""),
        "parent_app_name": feature.get("parent_app_name", ""),
        "feature_name_cn": feature.get("feature_name_cn", ""),
        "selected_template": feature.get("selected_template", ""),
        "final_score": final_score,
        "confidence_score": confidence,
        "recommendation": recommendation,
        "one_sentence_opportunity": _one_sentence(feature, candidate),
        "user_scenario": _user_scenario(feature),
        "mvp_scope": _mvp_scope(feature),
        "evidence": _build_evidence(candidate),
        "risk_summary": risk_summary,
        "risk_flags": risk_flags,
        "reason": list(feature.get("reason", []) or []),
        "target_platforms": feature.get("target_platforms", []) or [],
        "created_at": _now_iso(),
    }


def build_briefs(ranked_features: list[dict], candidates_by_key: dict[str, dict],
                 date_str: str | None = None) -> list[dict]:
    """对 ranked features 批量生成 briefs（含 produce/review/skip 全部，便于复盘）。"""
    date_str = date_str or datetime.now().strftime("%Y%m%d")
    briefs: list[dict] = []
    seq = 0
    for feat in ranked_features:
        cand = candidates_by_key.get(feat.get("parent_app_key", ""), {})
        seq += 1
        briefs.append(build_brief(feat, cand, seq, date_str))
    return briefs


def brief_stats(briefs: list[dict]) -> dict:
    """brief 汇总统计（写入 crawl-report）。"""
    total = len(briefs)
    produce = sum(1 for b in briefs if b["recommendation"] == "produce")
    review = sum(1 for b in briefs if b["recommendation"] == "review")
    skip = sum(1 for b in briefs if b["recommendation"] == "skip")
    avg_conf = round(sum(b["confidence_score"] for b in briefs) / total, 1) if total else 0
    return {"total": total, "produce": produce, "review": review, "skip": skip,
            "avg_confidence": avg_conf}
