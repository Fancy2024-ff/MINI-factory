"""core.opportunity.feature_extraction_llm — LLM 驱动的功能拆分器。

对单个 App 调一次 LLM，注入真实 name/description/features/category，强制 JSON schema
输出贴合该 App 的功能列表。pydantic 严格校验，经 ability_map 回填落地层，返回全量
FeatureSpec(Top-N 截断只在入队 buildable 项时施加，不截断复盘清单)。

任何失败(LLM 不可用/超时/schema 校验失败/越界 ability_type)由门面层整体回退规则版。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.integrations.llm import get_llm
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
# 产品策略值(设计 §3.2/§4.2)，调参在此一处改。
_FIT_BY_COMPLEXITY = {"easy": 86, "medium": 78, "hard": 60}
_VIRAL_BY_COMPLEXITY = {"easy": 75, "medium": 70, "hard": 60}
_FIT_THRESHOLD = 65  # production_recommended 的 fit 门槛(产品策略值 §3.2/§4.2)
_FIT_UNBUILDABLE = 35  # buildable=false：低于门槛，确保被闸门 A(ranking) 挡住，不进生产队列
_FIT_DEFAULT = 70  # complexity 越界时的兜底 fit
_VIRAL_DEFAULT = 65  # complexity 越界时的兜底 viral


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
    fit = _FIT_BY_COMPLEXITY.get(f.complexity, _FIT_DEFAULT) if land["buildable"] else _FIT_UNBUILDABLE
    viral = _VIRAL_BY_COMPLEXITY.get(f.complexity, _VIRAL_DEFAULT)
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


_LLM_TIMEOUT_SECONDS = 30
_LLM_MAX_RETRIES = 2
_DEFAULT_TOP_N = 5

_cache: dict[str, list[dict]] = {}


def _clear_cache() -> None:
    _cache.clear()


def _build_prompt(app: dict) -> str:
    """注入 App 真实信息，要求只输出 ABILITY_TYPES 内的 ability_type。"""
    enum = ", ".join(sorted(ABILITY_TYPES))
    feats = "; ".join(app.get("features", []) or [])
    return (
        "你是小程序工厂的功能拆分器。给定一个 App 的真实信息，拆出它包含的、可独立做成"
        "轻量小程序的功能。只输出 JSON，格式 {\"features\": [...]}，每个 feature 含字段："
        "feature_name, feature_name_cn, description, ability_type, input_modality(数组), "
        "output_modality, complexity, extraction_confidence(0~1)。\n"
        f"ability_type 只能从这个封闭集合里选(不得自创)：{enum}\n"
        "处理已上传图/视频/音频的语义用 image-edit/video-edit/audio-edit，"
        "凭文字生成新内容用 image-gen/text-gen 等。贴合该 App 真实功能，不要套预设模板。\n\n"
        f"App 名称：{app.get('name', '')}\n"
        f"分类：{app.get('category', '') or ' '.join(app.get('categories', []) or [])}\n"
        f"描述：{app.get('description', '')}\n"
        f"功能点：{feats}\n"
    )


def _call_llm(app: dict) -> "LLMFeatureList":
    """调 LLM 并解析为 LLMFeatureList。超时+重试；任何失败抛异常(门面层回退)。"""
    # default_request_timeout(别名 timeout)是 ChatAnthropic 的真实超时字段；
    # with_config({"timeout":...}) 不是 RunnableConfig 合法字段会被静默忽略，故用 model_copy 注入。
    llm = get_llm(max_tokens=4096).model_copy(update={"default_request_timeout": float(_LLM_TIMEOUT_SECONDS)})
    prompt = _build_prompt(app)
    last_err: Exception | None = None
    for _ in range(_LLM_MAX_RETRIES + 1):
        try:
            resp = llm.invoke(prompt)
            raw = resp.content if isinstance(resp.content, str) else str(resp.content)
            m = re.search(r"\{.*\}", raw, re.S)   # 容忍 ```json 包裹/前后散文，提取首个 JSON 对象
            if not m:
                raise ValueError("LLM 未返回可解析 JSON")
            data = json.loads(m.group(0))
            return LLMFeatureList(**data)  # pydantic 严格校验，越界 ability_type 在此抛错
        except Exception as e:  # noqa: BLE001 — 统一捕获，交由门面整体回退
            last_err = e
    raise RuntimeError(f"LLM 拆分失败: {last_err}")


def extract_features_llm(app: dict, top_n: int = _DEFAULT_TOP_N) -> list[dict]:
    """对单个 App 用 LLM 拆出全量 FeatureSpec。

    Top-N 只约束入队的 buildable 项(按 fit 降序取 top_n，其余 buildable 降级
    production_recommended=False 但仍保留)；buildable=false 全量进复盘清单不截断。
    失败抛异常，由 extract_all 门面整体回退规则版。
    """
    parent_key = app.get("canonical_key", "")
    if parent_key and parent_key in _cache:
        return [dict(s) for s in _cache[parent_key]]

    parsed = _call_llm(app)
    parent_name = app.get("name", "")
    specs = [build_feature_spec(f, parent_key, parent_name) for f in parsed.features]

    # Top-N：只对 buildable=true 排序截断，超出名额的降 production_recommended(不丢弃)
    buildable = [s for s in specs if s["buildable"]]
    buildable.sort(key=lambda s: s["miniapp_fit_score"], reverse=True)
    for s in buildable[top_n:]:   # 超出 Top-N 名额的 buildable 项降级(仍保留在返回列表)
        s["production_recommended"] = False

    if parent_key:
        _cache[parent_key] = [dict(s) for s in specs]
    return specs
