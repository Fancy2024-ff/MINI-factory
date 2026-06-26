"""core.opportunity.feature_extraction_llm — LLM 驱动的功能拆分器。

对单个 App 调一次 LLM，注入真实 name/description/features/category，强制 JSON schema
输出贴合该 App 的功能列表。pydantic 严格校验，经 ability_map 回填落地层，返回全量
FeatureSpec(Top-N 截断只在入队 buildable 项时施加，不截断复盘清单)。

任何失败(LLM 不可用/超时/schema 校验失败/越界 ability_type)由门面层整体回退规则版。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.opportunity.ability_map import ABILITY_TYPES

_Modality = Literal["text", "image", "video", "audio", "multi-field"]
_OutModality = Literal["text", "image", "video", "audio"]
_Complexity = Literal["easy", "medium", "hard"]


class LLMFeature(BaseModel):
    """LLM 抽取的单个功能(语义层)。落地层由 ability_map 回填，不由 LLM 产出。"""
    feature_name: str = Field(min_length=1)
    feature_name_cn: str = Field(min_length=1)
    description: str = Field(min_length=1)
    ability_type: str
    input_modality: list[_Modality] = Field(min_length=1)
    output_modality: _OutModality
    complexity: _Complexity
    extraction_confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("ability_type")
    @classmethod
    def _ability_in_enum(cls, v: str) -> str:
        if v not in ABILITY_TYPES:
            raise ValueError(f"ability_type 越界: {v}")
        return v


class LLMFeatureList(BaseModel):
    features: list[LLMFeature] = Field(min_length=1)  # 空列表视为抽取失败，交门面层回退规则版
