"""core.generator.feature_input 测试 — FeatureOpportunity 归一化契约。"""

from __future__ import annotations

from core.generator.feature_input import (
    INPUT_FEATURE_OPPORTUNITY,
    is_feature_opportunity,
    normalize_feature_opportunity,
)


_FEAT = {
    "feature_key": "app_store:123456789:ai_photo_retouch",
    "parent_app_name": "CapCut",
    "feature_name": "AI photo retouch",
    "feature_name_cn": "AI 修图",
    "description": "从大型视频编辑 App 中拆出的轻量 AI 修图能力",
    "selected_template": "ai-image",
    "viral_score": 78,
    "opportunity_score": 82,
    "miniapp_fit_score": 86,
    "reason": ["功能轻量，适合即用即走", "父 App 热度高，需求已验证", "图片结果适合分享传播"],
}


def test_is_feature_opportunity_detection():
    assert is_feature_opportunity(_FEAT) is True
    assert is_feature_opportunity({"name": "Some App", "features": ["x"]}) is False
    assert is_feature_opportunity({}) is False


def test_feature_name_drives_product_not_parent_app():
    """核心产品规则：小程序主体是被拆出的功能，不是父 App。"""
    app = normalize_feature_opportunity(_FEAT)
    # name/name_cn 应是功能名，不是 CapCut
    assert app["name_cn"] == "AI 修图"
    assert "CapCut" not in app["name_cn"]
    assert "CapCut" not in app["name"]
    # 父 App 仅作来源元信息保留
    assert app["parent_app_name"] == "CapCut"
    assert app["feature_name_cn"] == "AI 修图"


def test_normalized_fields_complete_for_downstream():
    app = normalize_feature_opportunity(_FEAT)
    # 下游通用字段齐全且非空
    for k in ("name", "name_cn", "category", "description", "description_cn",
              "features", "features_cn", "monetization"):
        assert app[k], f"{k} 不应为空"
    assert app["features_cn"][0] == "AI 修图"  # 功能本身在首位
    assert len(app["features_cn"]) >= 2
    # 元信息
    assert app["input_type"] == INPUT_FEATURE_OPPORTUNITY
    assert app["feature_key"] == _FEAT["feature_key"]
    assert app["selected_template"] == "ai-image"


def test_missing_description_synthesized_with_feature_and_parent():
    feat = dict(_FEAT)
    feat.pop("description")
    app = normalize_feature_opportunity(feat)
    assert app["description"]
    assert "AI 修图" in app["description"]
    assert "CapCut" in app["description"]  # 来源标注


def test_minimal_feature_input_does_not_crash():
    app = normalize_feature_opportunity({"feature_name_cn": "背景去除"})
    assert app["name_cn"] == "背景去除"
    assert app["features_cn"]  # 非空
    assert app["selected_template"] == ""  # 上游未给，留空让 classifier 判断
