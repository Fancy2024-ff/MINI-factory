"""core.opportunity.feature_extraction_llm — LLM 驱动的功能拆分器。

对单个 App 调一次 LLM，注入真实 name/description/features/category，强制 JSON schema
输出贴合该 App 的功能列表。pydantic 严格校验，经 ability_map 回填落地层，返回全量
FeatureSpec(Top-N 截断只在入队 buildable 项时施加，不截断复盘清单)。

任何失败(LLM 不可用/超时/schema 校验失败/越界 ability_type)由门面层整体回退规则版。
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.opportunity.ability_map import ABILITY_TYPES, resolve

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


# fit/viral 基线：按 complexity 给保守默认(LLM 不打分，避免幻觉数字)。
_FIT_BY_COMPLEXITY = {"easy": 86, "medium": 78, "hard": 60}
_VIRAL_BY_COMPLEXITY = {"easy": 75, "medium": 70, "hard": 60}
_FIT_THRESHOLD = 65  # production_recommended 的 fit 门槛


def _slug(s: str) -> str:
    """url-safe slug；纯非 ASCII 清洗后为空时用稳定短哈希兜底(对齐 feature_registry)。"""
    original = s or ""
    slug = re.sub(r"[^a-z0-9]+", "-", original.lower()).strip("-")
    if slug:
        return slug
    digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
    return f"feature-{digest}"


def _stable_feature_key(parent_key: str, feature_name: str) -> str:
    """feature_key = <parent_key>:<slug(feature_name)>。不含 ability_type(LLM 不稳定)，
    保证同 App 同功能恒定，不破坏 processed_apps 去重。"""
    return f"{parent_key}:{_slug(feature_name)}"


def build_feature_spec(f: "LLMFeature", parent_key: str, parent_name: str) -> dict:
    """把校验过的 LLMFeature + ability_map 落地信息合成一条完整 FeatureSpec。"""
    land = resolve(f.ability_type)  # 越界已在 schema 拦截，这里安全
    fit = _FIT_BY_COMPLEXITY.get(f.complexity, 70) if land["buildable"] else 35
    viral = _VIRAL_BY_COMPLEXITY.get(f.complexity, 65)
    production_recommended = bool(land["buildable"]) and fit >= _FIT_THRESHOLD
    return {
        "feature_key": _stable_feature_key(parent_key, f.feature_name),
        "parent_app_key": parent_key,
        "parent_app_name": parent_name,
        "feature_name": f.feature_name,
        "feature_name_cn": f.feature_name_cn,
        "description": f.description,
        "ability_type": f.ability_type,
        "input_modality": list(f.input_modality),
        "output_modality": f.output_modality,
        "complexity": f.complexity,
        "extraction_confidence": f.extraction_confidence,
        "buildable": land["buildable"],
        "auto_publishable": land["auto_publishable"],
        "selected_template": land["selected_template"],
        "required_capabilities": land["required_capabilities"],
        "unsupported_reasons": land["unsupported_reasons"],
        "miniapp_fit_score": fit,
        "viral_score": viral,
        "production_recommended": production_recommended,
        "reason": [f"从 {parent_name} 拆出的功能：{f.feature_name_cn}"],
        "data_source": "llm",
    }
