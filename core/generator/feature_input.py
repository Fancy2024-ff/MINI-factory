"""core.generator.feature_input — 小程序生成板块的输入契约（capability-domain）。

生成板块的上游有两类输入，本模块把它们归一化成下游（classifier / prd_builder /
codegen / growth）统一消费的 dict，避免每个域各自判断输入形态：

  1. AppCandidate —— 直接把一个 App 小程序化（已有流程）。
  2. FeatureOpportunity —— 从大 App 中拆出一个功能做小程序（生产工厂核心）。

关键产品规则（FeatureOpportunity）：
  小程序名称 / 功能说明 / 文案要突出「被拆出的功能」，而不是父 App 名称。
  例：CapCut 的 AI 修图 → 产品是「AI 修图」小程序，不是「剪映小程序」。

归一化后保留 feature 元信息（input_type / feature_key / parent_app_name /
feature_name_cn / selected_template），供 prd_builder 与 codegen-report 使用。
"""

from __future__ import annotations

from typing import Any

INPUT_APP_CANDIDATE = "app_candidate"
INPUT_FEATURE_OPPORTUNITY = "feature_opportunity"


def is_feature_opportunity(raw: dict[str, Any]) -> bool:
    """判定一条输入是否为 FeatureOpportunity。以 feature_key / feature_name 为标志。"""
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("feature_key") or raw.get("feature_name") or raw.get("feature_name_cn"))


def normalize_feature_opportunity(feat: dict[str, Any]) -> dict[str, Any]:
    """把 FeatureOpportunity 归一化成下游统一 app dict。

    产品语义：name/name_cn/description 以「被拆出的功能」为主体，父 App 仅作来源标注，
    不让生成物变成「父 App 小程序」。features_cn 至少含该功能本身，保证非空。
    """
    feat = dict(feat or {})

    feature_name = (feat.get("feature_name") or "").strip()
    feature_name_cn = (feat.get("feature_name_cn") or "").strip() or feature_name or "AI 工具"
    feature_name_en = feature_name or feature_name_cn
    parent_app = (feat.get("parent_app_name") or "").strip()
    desc = (feat.get("description") or "").strip()
    if not desc:
        desc = (
            f"从 {parent_app} 拆出的轻量功能「{feature_name_cn}」，做成即用即走的小程序。"
            if parent_app else f"轻量功能「{feature_name_cn}」小程序。"
        )

    # features_cn：功能本身 + reason 里能用的要点（去重、非空）
    features_cn: list[str] = [feature_name_cn]
    for r in (feat.get("reason") or []):
        if isinstance(r, str) and r.strip() and r.strip() not in features_cn:
            features_cn.append(r.strip())
    if len(features_cn) < 2:
        features_cn.append("结果一键保存 / 分享")

    app: dict[str, Any] = {
        # 下游通用字段：以功能为主体（不是父 App 名）
        "name": feature_name_en,
        "name_cn": feature_name_cn,
        "category": feat.get("category", "") or "Utilities",
        "description": desc,
        "description_cn": desc,
        "features": list(features_cn),
        "features_cn": list(features_cn),
        "downloads": feat.get("downloads", 0) or 0,
        "rating": feat.get("rating", 0) or 0,
        "review_count": feat.get("review_count", 0) or 0,
        "monetization": feat.get("monetization") or "freemium",
        # feature 元信息（保留给 prd_builder / codegen-report）
        "input_type": INPUT_FEATURE_OPPORTUNITY,
        "feature_key": feat.get("feature_key", ""),
        "parent_app_name": parent_app,
        "feature_name": feature_name_en,
        "feature_name_cn": feature_name_cn,
        "reason": list(feat.get("reason") or []),
        # 上游已选模板（classifier 应优先尊重）
        "selected_template": (feat.get("selected_template") or "").strip(),
        # 上游分数（可选，供 scoring 交叉印证）
        "viral_score": feat.get("viral_score"),
        "opportunity_score": feat.get("opportunity_score"),
        "miniapp_fit_score": feat.get("miniapp_fit_score"),
        # 溯源（queue 消费时保留：哪条队列项、对应 feature_key）。
        # 与旧 queue_item_to_app_input 字段名兼容，便于 queue 状态回写与测试断言。
        "source_queue_id": feat.get("queue_id", "") or feat.get("source_queue_id", ""),
        "source_feature_key": feat.get("feature_key", "") or feat.get("source_feature_key", ""),
    }
    return app
