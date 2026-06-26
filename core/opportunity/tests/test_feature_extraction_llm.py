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
