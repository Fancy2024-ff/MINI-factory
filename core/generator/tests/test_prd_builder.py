"""core.generator.prd_builder 测试 — App 级 + Feature 级 PRD。"""

from __future__ import annotations

from core.generator.prd_builder import build_prd

_OPP = {
    "opportunity_score": 82,
    "target_platforms": ["wechat"],
    "estimated_dev_days": 6,
}


def test_app_level_prd_still_works():
    """回归：AppCandidate 级 PRD 不破坏。"""
    app = {
        "name": "AI Writer", "name_cn": "AI 写作", "description_cn": "写作助手",
        "features_cn": ["语法纠正", "翻译"], "input_type": "app_candidate",
    }
    md, js = build_prd(app, _OPP)
    assert "AI 写作" in md
    assert js["product_type"] == "miniapp"
    assert js["core_features"] == ["语法纠正", "翻译"]


def _feature_app():
    # 模拟 normalize_feature_opportunity 的输出
    return {
        "name": "AI photo retouch", "name_cn": "AI 修图",
        "description": "从 CapCut 拆出的轻量 AI 修图", "description_cn": "从 CapCut 拆出的轻量 AI 修图",
        "features_cn": ["AI 修图", "图片结果适合分享传播"],
        "input_type": "feature_opportunity",
        "feature_key": "app_store:123:ai_photo_retouch",
        "parent_app_name": "CapCut",
        "feature_name": "AI photo retouch", "feature_name_cn": "AI 修图",
        "selected_template": "ai-image",
        "reason": ["功能轻量，适合即用即走", "图片结果适合分享传播"],
    }


def test_feature_prd_product_is_feature_not_parent():
    """核心：产品主体是被拆功能（AI 修图），不是父 App（CapCut）。"""
    md, js = build_prd(_feature_app(), _OPP)
    # 标题/产品名是功能
    assert md.startswith("# AI 修图 小程序")
    assert js["app_name_cn"] == "AI 修图"
    # 父 App 仅作来源标注，不作为产品名
    assert js["parent_app_name"] == "CapCut"
    assert "非「CapCut」整体" in md


def test_feature_prd_has_non_goals_and_boundary():
    """feature PRD 必含非目标功能 + 技术边界（不承诺做成完整父 App）。"""
    md, js = build_prd(_feature_app(), _OPP)
    assert "非目标功能" in md
    assert "技术边界" in md
    assert "上架风险" in md
    assert "增长点" in md
    # ai-image 模板的非目标含「完整视频剪辑」
    assert any("视频剪辑" in g for g in js["non_goals"])
    assert js["input_type"] == "feature_opportunity"
    assert js["feature_key"] == "app_store:123:ai_photo_retouch"
    assert js["selected_template"] == "ai-image"


def test_feature_prd_mvp_focuses_single_feature():
    md, js = build_prd(_feature_app(), _OPP)
    # MVP 聚焦单一功能
    assert any("AI 修图" in m for m in js["mvp_features"])
    assert "MVP 功能" in md
