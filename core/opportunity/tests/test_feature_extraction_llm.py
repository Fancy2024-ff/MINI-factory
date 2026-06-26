"""LLM 功能拆分器测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.opportunity import feature_extraction_llm as fx


def test_llm_feature_schema_accepts_valid():
    f = fx.LLMFeature(
        feature_name="Background Remover", feature_name_cn="背景去除",
        description="一键去除图片背景", ability_type="bg-remove",
        input_modality=["image"], output_modality="image",
        complexity="easy", extraction_confidence=0.9,
    )
    assert f.ability_type == "bg-remove"


def test_llm_feature_schema_rejects_out_of_enum_ability():
    """越界 ability_type 必须校验失败(供整体回退)。"""
    with pytest.raises(ValidationError):
        fx.LLMFeature(
            feature_name="X", feature_name_cn="X", description="x",
            ability_type="totally-made-up", input_modality=["text"],
            output_modality="text", complexity="easy", extraction_confidence=0.5,
        )


def test_llm_feature_schema_rejects_bad_confidence():
    with pytest.raises(ValidationError):
        fx.LLMFeature(
            feature_name="X", feature_name_cn="X", description="x",
            ability_type="text-gen", input_modality=["text"],
            output_modality="text", complexity="easy", extraction_confidence=5.0,
        )


def test_llm_feature_list_rejects_empty():
    """LLM 返回空功能列表视为失败(供整体回退)。"""
    with pytest.raises(ValidationError):
        fx.LLMFeatureList(features=[])


def test_feature_key_stable_across_calls():
    """同 App 同功能两次抽取 feature_key 必须恒定(保 processed-apps 去重)。"""
    k1 = fx._stable_feature_key("app_store:123", "Background Remover")
    k2 = fx._stable_feature_key("app_store:123", "Background Remover")
    assert k1 == k2 == "app_store:123:background-remover"


def test_feature_key_non_ascii_hash_fallback():
    """纯非 ASCII 功能名清洗后为空 → 稳定哈希兜底，不塌缩。"""
    k1 = fx._stable_feature_key("app_store:1", "背景去除")
    k2 = fx._stable_feature_key("app_store:1", "背景去除")
    assert k1 == k2
    assert k1.startswith("app_store:1:")
    # 不同功能名得到不同 key
    assert fx._stable_feature_key("app_store:1", "背景去除") != fx._stable_feature_key("app_store:1", "去水印")


def test_build_feature_spec_backfills_landing_layer():
    """build_feature_spec 用 ability_map 回填 buildable/template/auto_publishable。"""
    llm_f = fx.LLMFeature(
        feature_name="Background Remover", feature_name_cn="背景去除",
        description="去背景", ability_type="bg-remove", input_modality=["image"],
        output_modality="image", complexity="easy", extraction_confidence=0.9,
    )
    spec = fx.build_feature_spec(llm_f, parent_key="app_store:123", parent_name="CapCut")
    assert spec["feature_key"] == "app_store:123:background-remover"
    assert spec["buildable"] is True
    assert spec["auto_publishable"] is True
    assert spec["selected_template"] == "background-remover"
    assert spec["data_source"] == "llm"


def test_build_feature_spec_unbuildable_no_template():
    """buildable=false(image-edit)：无模板、production_recommended=false、带 unsupported_reasons。"""
    llm_f = fx.LLMFeature(
        feature_name="Old Photo Restore", feature_name_cn="老照片修复",
        description="修复老照片", ability_type="image-edit", input_modality=["image"],
        output_modality="image", complexity="medium", extraction_confidence=0.8,
    )
    spec = fx.build_feature_spec(llm_f, parent_key="app_store:9", parent_name="Remini")
    assert spec["buildable"] is False
    assert spec["selected_template"] == ""
    assert spec["production_recommended"] is False
    assert spec["unsupported_reasons"]
