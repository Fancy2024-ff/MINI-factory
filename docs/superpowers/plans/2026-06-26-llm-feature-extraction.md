# LLM 功能拆分器 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 14 个预设关键词匹配的功能拆分器，换成 LLM 语义抽取，对任意 App 产出贴合其真实功能的结构化 FeatureSpec，规则版作为全量 fallback。

**架构：** 三个文件。`ability_map.py` 是 B/C 共用的封闭枚举 + 映射真源（§4 那张表）。`feature_extraction_llm.py` 调 LLM → pydantic 严格校验 → 经 ability_map 回填落地层 → 返回全量 FeatureSpec。`feature_extraction.py` 的 `extract_all(candidates, enrich=False)` 改门面：enrich=True 走 LLM、任何失败整体回退规则版，产物打 `data_source`。下游 crawl_runner 不改。

**技术栈：** Python 3.11，pydantic 2.13，langchain-anthropic（复用 `core/integrations/llm.py:get_llm`），pytest（`.venv/bin/python -m pytest`）。

**红线（并行开发期）：** 只动 `core/opportunity/` 下这几个文件 + 只读复用 `core/integrations/llm.py`。不碰 `core/generator/`、`core/qa/`、`apps/api/main.py`、`core/pipeline/task_worker.py`。

**运行测试统一命令：** 从 repo 根 `cd /Users/apple/MINI-factory && .venv/bin/python -m pytest <path> -v`

---

## 文件结构

| 文件 | 职责 | 操作 |
|---|---|---|
| `core/opportunity/ability_map.py` | ABILITY_TYPES 封闭枚举 + 映射表（ability_type → template/caps/buildable/auto_publishable）。B/C 唯一真源。 | 创建 |
| `core/opportunity/tests/test_ability_map.py` | 校验映射表与 _KNOWN_TEMPLATES / TASK_WHITELIST 对齐、铁律（无 text2img 误映射） | 创建 |
| `core/opportunity/feature_extraction_llm.py` | LLM 抽取器：prompt 构造、pydantic schema、调用（超时/重试/缓存）、回填落地层、feature_key 稳定生成、规则 fallback 触发 | 创建 |
| `core/opportunity/tests/test_feature_extraction_llm.py` | schema 校验+fallback、feature_key 稳定性、Top-N、回填正确性 | 创建 |
| `core/opportunity/feature_extraction.py` | `extract_all(candidates, enrich=False)` 改门面；规则版产物补 `data_source`/`auto_publishable` 字段 | 修改 |
| `core/opportunity/tests/test_feature_extraction.py` | 闸门 A（buildable=false 不进 ranked）、门面 fallback、CapCut 端到端 | 修改（追加） |

每个任务产出独立、可测试的变更。Task 1 先固化 ability_map（C 的关键依赖，接口稳定优先）。

---

## 任务 1：ability_map.py — 封闭枚举 + 映射真源

**文件：**
- 创建：`core/opportunity/ability_map.py`
- 测试：`core/opportunity/tests/test_ability_map.py`

- [ ] **步骤 1：编写失败的测试**

创建 `core/opportunity/tests/test_ability_map.py`：

```python
"""ability_map 映射真源测试：与现有白名单对齐 + 铁律(无 text2img 误映射)。"""

from __future__ import annotations

from core.opportunity import ability_map as am
from core.opportunity.classifier import _KNOWN_TEMPLATES, _TEMPLATE_ABILITY_TASK
from core.publisher.feature_registry import TASK_WHITELIST


def test_buildable_templates_in_known_templates():
    """所有 buildable=true 的 selected_template 必须 ∈ classifier._KNOWN_TEMPLATES。"""
    for at, m in am.ABILITY_MAP.items():
        if m["buildable"]:
            assert m["selected_template"] in _KNOWN_TEMPLATES, f"{at} 模板不在白名单"


def test_ability_task_consistent_with_classifier():
    """buildable 项的 (ability, task) 与 classifier._TEMPLATE_ABILITY_TASK 一致。"""
    for at, m in am.ABILITY_MAP.items():
        if m["buildable"]:
            ab, tk = _TEMPLATE_ABILITY_TASK.get(m["selected_template"], ("text2img", "pending"))
            assert (m["ability"], m["task"]) == (ab, tk), f"{at} ability/task 不一致"


def test_auto_publishable_iff_task_in_whitelist():
    """auto_publishable=true 当且仅当 task ∈ TASK_WHITELIST。"""
    for at, m in am.ABILITY_MAP.items():
        assert m["auto_publishable"] == (m["task"] in TASK_WHITELIST), f"{at} auto_publishable 错"


def test_iron_rule_no_edit_semantics_map_to_text2img():
    """铁律：处理已有素材的语义(image-edit/video/audio/camera/3d/multi-step)绝不 buildable。"""
    for at in ["image-edit", "video-edit", "audio-edit", "realtime-camera", "3d-ar", "multi-step"]:
        assert am.ABILITY_MAP[at]["buildable"] is False, f"{at} 不应 buildable"
        assert am.ABILITY_MAP[at]["selected_template"] == "", f"{at} 不应有模板"
        assert am.ABILITY_MAP[at]["unsupported_reasons"], f"{at} 应有 unsupported_reasons"


def test_enum_closed_and_resolve():
    """resolve 越界 ability_type 抛 KeyError(供 schema 校验失败 → fallback)。"""
    assert "image-gen" in am.ABILITY_TYPES
    import pytest
    with pytest.raises(KeyError):
        am.resolve("nonexistent-type")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_ability_map.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'core.opportunity.ability_map'`

- [ ] **步骤 3：编写最少实现代码**

创建 `core/opportunity/ability_map.py`：

```python
"""core.opportunity.ability_map — ability_type 封闭枚举 + 落地映射真源。

B(功能拆分)与 C(generator)共用的唯一真源，杜绝并行枚举。LLM 只能产 ABILITY_TYPES
内的 ability_type(超出 = schema 校验失败 → 走规则 fallback)。

铁律(§4.0)：任何"处理一张已上传的图/视频/音频"语义(image-edit/video-edit/...)
绝不映射到 text2img 文生图模板。项目里图生图真实能力只有 background_remove /
watermark_remove 两个具体 task，通用图生图无对应后端，故 buildable=false。

落地分两层(§4.1)：
- buildable      = 能否产出可渲染小程序(模板 ∈ classifier._KNOWN_TEMPLATES)
- auto_publishable = 后端 task 是否 ∈ feature_registry.TASK_WHITELIST(名副其实可自动上线)
  buildable=true 但 auto_publishable=false 的(avatar 等)入队但标 review_required，不自动上线。
"""

from __future__ import annotations

# ability_type -> 落地信息。buildable=true 的 selected_template 必须 ∈ _KNOWN_TEMPLATES，
# (ability, task) 必须与 classifier._TEMPLATE_ABILITY_TASK 一致(test_ability_map 强校验)。
ABILITY_MAP: dict[str, dict] = {
    # —— buildable=true：生成新内容语义，落 text2img/img2img ——
    "image-gen": {"selected_template": "ai-image", "ability": "text2img", "task": "generate_image",
                  "buildable": True, "auto_publishable": True,
                  "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "bg-remove": {"selected_template": "background-remover", "ability": "img2img", "task": "background_remove",
                  "buildable": True, "auto_publishable": True,
                  "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "watermark-remove": {"selected_template": "watermark-remover", "ability": "img2img", "task": "watermark_remove",
                         "buildable": True, "auto_publishable": True,
                         "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "avatar-gen": {"selected_template": "avatar-viral", "ability": "text2img", "task": "pending",
                   "buildable": True, "auto_publishable": False,
                   "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "sticker-gen": {"selected_template": "sticker-viral", "ability": "text2img", "task": "pending",
                    "buildable": True, "auto_publishable": False,
                    "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "pet-talk": {"selected_template": "pet-talk-viral", "ability": "text2img", "task": "pending",
                 "buildable": True, "auto_publishable": False,
                 "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "blessing": {"selected_template": "blessing-video-viral", "ability": "text2img", "task": "pending",
                 "buildable": True, "auto_publishable": False,
                 "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "funny-video": {"selected_template": "funny-video-viral", "ability": "text2img", "task": "pending",
                    "buildable": True, "auto_publishable": False,
                    "required_capabilities": ["image_generation"], "unsupported_reasons": []},
    "text-gen": {"selected_template": "ai-tool", "ability": "text2img", "task": "pending",
                 "buildable": True, "auto_publishable": False,
                 "required_capabilities": ["llm"], "unsupported_reasons": []},
    # —— buildable=false：处理已有素材/重能力，无后端落点，记录不入队 ——
    "image-edit": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["image_edit"],
                   "unsupported_reasons": ["通用图生图无对应后端 task，仅 bg-remove/watermark-remove 可落地"]},
    "video-edit": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["video_render"],
                   "unsupported_reasons": ["缺视频处理 provider", "长视频转码成本高"]},
    "audio-edit": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["audio_process"],
                   "unsupported_reasons": ["缺音频处理 provider"]},
    "realtime-camera": {"selected_template": "", "ability": "", "task": "",
                        "buildable": False, "auto_publishable": False,
                        "required_capabilities": ["realtime_camera"],
                        "unsupported_reasons": ["实时/AR 相机依赖原生能力，小程序端难稳定支持"]},
    "3d-ar": {"selected_template": "", "ability": "", "task": "",
              "buildable": False, "auto_publishable": False,
              "required_capabilities": ["3d_render"],
              "unsupported_reasons": ["3D/AR 渲染重，第一阶段不做"]},
    "multi-step": {"selected_template": "", "ability": "", "task": "",
                   "buildable": False, "auto_publishable": False,
                   "required_capabilities": ["workflow"],
                   "unsupported_reasons": ["多步复杂工作流暂不可单步落地"]},
}

# 封闭枚举：LLM 只能从中选 ability_type。
ABILITY_TYPES = frozenset(ABILITY_MAP.keys())


def resolve(ability_type: str) -> dict:
    """返回 ability_type 的落地信息副本。越界抛 KeyError(供上游触发 fallback)。"""
    return dict(ABILITY_MAP[ability_type])
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_ability_map.py -v`
预期：PASS（5 passed）

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/ability_map.py core/opportunity/tests/test_ability_map.py
git commit -m "feat(opportunity): ability_map 封闭枚举+映射真源(B/C 共用,铁律禁 text2img 误映射)"
```

---

## 任务 2：FeatureSpec pydantic schema

**文件：**
- 修改：`core/opportunity/feature_extraction_llm.py`（创建，本任务只放 schema 部分）
- 测试：`core/opportunity/tests/test_feature_extraction_llm.py`（创建）

- [ ] **步骤 1：编写失败的测试**

创建 `core/opportunity/tests/test_feature_extraction_llm.py`：

```python
"""LLM 功能拆分器测试。"""

from __future__ import annotations

import pytest

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
    with pytest.raises(Exception):
        fx.LLMFeature(
            feature_name="X", feature_name_cn="X", description="x",
            ability_type="totally-made-up", input_modality=["text"],
            output_modality="text", complexity="easy", extraction_confidence=0.5,
        )


def test_llm_feature_schema_rejects_bad_confidence():
    with pytest.raises(Exception):
        fx.LLMFeature(
            feature_name="X", feature_name_cn="X", description="x",
            ability_type="text-gen", input_modality=["text"],
            output_modality="text", complexity="easy", extraction_confidence=5.0,
        )
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'core.opportunity.feature_extraction_llm'`

- [ ] **步骤 3：编写最少实现代码**

创建 `core/opportunity/feature_extraction_llm.py`（仅 schema 部分，后续任务追加）：

```python
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
    features: list[LLMFeature]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -v`
预期：PASS（3 passed）

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/feature_extraction_llm.py core/opportunity/tests/test_feature_extraction_llm.py
git commit -m "feat(opportunity): FeatureSpec pydantic schema(ability_type 封闭枚举校验)"
```

---

## 任务 3：feature_key 稳定生成 + 回填落地层

**文件：**
- 修改：`core/opportunity/feature_extraction_llm.py`（追加 `_stable_feature_key` + `build_feature_spec`）
- 测试：`core/opportunity/tests/test_feature_extraction_llm.py`（追加）

- [ ] **步骤 1：编写失败的测试**

在 `test_feature_extraction_llm.py` 追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -k "feature_key or build_feature_spec" -v`
预期：FAIL，`AttributeError: module ... has no attribute '_stable_feature_key'`

- [ ] **步骤 3：编写最少实现代码**

在 `feature_extraction_llm.py` 追加（顶部 import 增加 `hashlib`、`re`、`from core.opportunity.ability_map import resolve`）：

```python
import hashlib
import re

from core.opportunity.ability_map import resolve

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
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -v`
预期：PASS（全部）

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/feature_extraction_llm.py core/opportunity/tests/test_feature_extraction_llm.py
git commit -m "feat(opportunity): feature_key 稳定生成 + ability_map 回填落地层"
```

---

## 任务 4：LLM 调用（超时/重试/缓存）+ Top-N + extract_features_llm

**文件：**
- 修改：`core/opportunity/feature_extraction_llm.py`（追加 prompt 构造、`_call_llm`、`extract_features_llm`、Top-N）
- 测试：`core/opportunity/tests/test_feature_extraction_llm.py`（追加，monkeypatch `_call_llm` 不打真网络）

- [ ] **步骤 1：编写失败的测试**

在 `test_feature_extraction_llm.py` 追加：

```python
def _capcut():
    return {"canonical_key": "app_store:123", "name": "CapCut",
            "description": "Video editor with background remover, AI avatar, auto captions for long video."}


def test_extract_features_llm_top_n_only_limits_buildable(monkeypatch):
    """Top-N 只截断入队 buildable 项；buildable=false 全量进复盘清单。"""
    # 造 6 个 buildable + 2 个 unbuildable
    feats = []
    for i in range(6):
        feats.append(fx.LLMFeature(
            feature_name=f"Gen {i}", feature_name_cn=f"生成{i}", description="d",
            ability_type="image-gen", input_modality=["text"], output_modality="image",
            complexity="easy", extraction_confidence=0.9))
    for i in range(2):
        feats.append(fx.LLMFeature(
            feature_name=f"Edit {i}", feature_name_cn=f"剪辑{i}", description="d",
            ability_type="video-edit", input_modality=["video"], output_modality="video",
            complexity="hard", extraction_confidence=0.85))
    monkeypatch.setattr(fx, "_call_llm", lambda app: fx.LLMFeatureList(features=feats))

    specs = fx.extract_features_llm(_capcut(), top_n=5)
    buildable_in_queue = [s for s in specs if s["production_recommended"]]
    unbuildable = [s for s in specs if not s["buildable"]]
    assert len(buildable_in_queue) == 5          # buildable 截到 5
    assert len(unbuildable) == 2                 # unbuildable 全量保留(不被 Top-N 截)


def test_extract_features_llm_raises_on_llm_failure(monkeypatch):
    """LLM 调用抛错时 extract_features_llm 向上抛(门面层据此整体回退规则版)。"""
    def _boom(app):
        raise RuntimeError("llm down")
    monkeypatch.setattr(fx, "_call_llm", _boom)
    with pytest.raises(RuntimeError):
        fx.extract_features_llm(_capcut())


def test_extract_features_llm_caches_by_canonical_key(monkeypatch):
    """同 canonical_key 第二次不再调 LLM(缓存)。"""
    fx._clear_cache()
    calls = {"n": 0}
    def _once(app):
        calls["n"] += 1
        return fx.LLMFeatureList(features=[fx.LLMFeature(
            feature_name="G", feature_name_cn="生成", description="d",
            ability_type="image-gen", input_modality=["text"], output_modality="image",
            complexity="easy", extraction_confidence=0.9)])
    monkeypatch.setattr(fx, "_call_llm", _once)
    fx.extract_features_llm(_capcut())
    fx.extract_features_llm(_capcut())
    assert calls["n"] == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -k "top_n or llm_failure or caches" -v`
预期：FAIL，`AttributeError: ... '_call_llm'` / `'extract_features_llm'`

- [ ] **步骤 3：编写最少实现代码**

在 `feature_extraction_llm.py` 追加（顶部 import 增加 `json`、`from core.integrations.llm import get_llm`）：

```python
import json

from core.integrations.llm import get_llm

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
    llm = get_llm(max_tokens=4096).with_config({"timeout": _LLM_TIMEOUT_SECONDS})
    prompt = _build_prompt(app)
    last_err: Exception | None = None
    for _ in range(_LLM_MAX_RETRIES + 1):
        try:
            resp = llm.invoke(prompt)
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1].lstrip("json").strip()
            data = json.loads(text)
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
    if parent_key in _cache:
        return [dict(s) for s in _cache[parent_key]]

    parsed = _call_llm(app)
    parent_name = app.get("name", "")
    specs = [build_feature_spec(f, parent_key, parent_name) for f in parsed.features]

    # Top-N：只对 buildable=true 排序截断，超出名额的降 production_recommended(不丢弃)
    buildable = [s for s in specs if s["buildable"]]
    buildable.sort(key=lambda s: s["miniapp_fit_score"], reverse=True)
    keep = {id(s) for s in buildable[:top_n]}
    for s in buildable:
        if id(s) not in keep:
            s["production_recommended"] = False

    _cache[parent_key] = [dict(s) for s in specs]
    return specs
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -v`
预期：PASS（全部）

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/feature_extraction_llm.py core/opportunity/tests/test_feature_extraction_llm.py
git commit -m "feat(opportunity): LLM 调用(超时/重试/缓存)+ Top-N 仅约束入队 buildable 项"
```

---

## 任务 5：feature_extraction.py 改门面 + 规则版补字段

**文件：**
- 修改：`core/opportunity/feature_extraction.py:90-160`（extract_features 补 `auto_publishable`/`data_source`；extract_all 改门面）
- 测试：`core/opportunity/tests/test_feature_extraction.py`（追加门面 fallback 测试）

- [ ] **步骤 1：编写失败的测试**

在 `core/opportunity/tests/test_feature_extraction.py` 追加：

```python
from core.opportunity.feature_extraction import extract_all
from core.opportunity import feature_extraction_llm as fx


def test_extract_all_rule_mode_default():
    """enrich=False(默认)走规则版，产物打 data_source=rule_fallback。"""
    feats = extract_all([_capcut()])
    assert feats
    assert all(f.get("data_source") == "rule_fallback" for f in feats)
    # 规则版产物也带 auto_publishable 字段(下游统一)
    assert all("auto_publishable" in f for f in feats)


def test_extract_all_enrich_falls_back_on_llm_failure(monkeypatch):
    """enrich=True 但 LLM 失败 → 整体回退规则版，不断流、不抛、不产脏数据。"""
    monkeypatch.setattr(fx, "extract_features_llm",
                        lambda app, top_n=5: (_ for _ in ()).throw(RuntimeError("down")))
    feats = extract_all([_capcut()], enrich=True)
    assert feats  # 不断流
    assert all(f.get("data_source") == "rule_fallback" for f in feats)


def test_extract_all_enrich_uses_llm_when_ok(monkeypatch):
    """enrich=True 且 LLM 正常 → 产物 data_source=llm。"""
    def _fake(app, top_n=5):
        return [{"feature_key": "app_store:123:bg", "parent_app_key": "app_store:123",
                 "parent_app_name": "CapCut", "feature_name": "BG", "feature_name_cn": "背景去除",
                 "ability_type": "bg-remove", "buildable": True, "auto_publishable": True,
                 "selected_template": "background-remover", "production_recommended": True,
                 "miniapp_fit_score": 86, "data_source": "llm",
                 "required_capabilities": ["image_generation"], "unsupported_reasons": []}]
    monkeypatch.setattr(fx, "extract_features_llm", _fake)
    feats = extract_all([_capcut()], enrich=True)
    assert all(f.get("data_source") == "llm" for f in feats)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction.py -k "extract_all" -v`
预期：FAIL（`extract_all()` 不接受 `enrich`，或规则产物无 `data_source`/`auto_publishable`）

- [ ] **步骤 3：编写最少实现代码**

3a. 在 `feature_extraction.py` 的 `extract_features` 里，给两处 `out.append({...})` 各补两个字段。`_DOABLE_FEATURES` 那条（约 :106-122）在 `"selected_template": template,` 同级补：

```python
            "auto_publishable": template in {"background-remover", "watermark-remover", "ai-image"},
            "data_source": "rule_fallback",
```

`_HARD_FEATURES` 那条（约 :128-144）在 `"selected_template": "",` 同级补：

```python
            "auto_publishable": False,
            "data_source": "rule_fallback",
```

3b. 把 `extract_all`（:155-160）改为门面：

```python
def extract_all(candidates: list[dict], enrich: bool = False) -> list[dict]:
    """对候选池所有 App 拆解，返回全部 FeatureOpportunity(含不推荐项，便于复盘)。

    enrich=False(默认): 规则版(向后兼容，crawl_runner 不改)。
    enrich=True: 逐 App 走 LLM 拆分器；任一 App LLM 失败则该 App 整体回退规则版，
    不断流、不抛、不产脏数据。
    """
    if not enrich:
        out: list[dict] = []
        for cand in candidates:
            out.extend(extract_features(cand))
        return out

    from core.opportunity import feature_extraction_llm as _llm

    out = []
    for cand in candidates:
        try:
            specs = _llm.extract_features_llm(cand)
            out.extend(specs)
        except Exception:  # noqa: BLE001 — LLM 失败 → 该 App 整体回退规则版
            out.extend(extract_features(cand))
    return out
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction.py -v`
预期：PASS（含原有规则版测试 + 新增门面测试）

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/feature_extraction.py core/opportunity/tests/test_feature_extraction.py
git commit -m "feat(opportunity): extract_all 改门面(enrich 走 LLM,失败整体回退规则版)+规则版补 data_source/auto_publishable"
```

---

## 任务 6：闸门 A 回归 + CapCut 端到端验证

**文件：**
- 测试：`core/opportunity/tests/test_feature_extraction_llm.py`（追加端到端 + 闸门 A）

- [ ] **步骤 1：编写失败的测试**

在 `test_feature_extraction_llm.py` 追加（验证 buildable=false 不进 ranked + CapCut 拆分形态）：

```python
from core.opportunity.ranking import rank_features


def test_gate_a_unbuildable_not_in_ranked(monkeypatch):
    """闸门 A：buildable=false(video-edit/image-edit)不进 rank_features，但在 extract 全量产物里。"""
    feats = [
        fx.LLMFeature(feature_name="Background Remover", feature_name_cn="背景去除",
                      description="去背景", ability_type="bg-remove", input_modality=["image"],
                      output_modality="image", complexity="easy", extraction_confidence=0.9),
        fx.LLMFeature(feature_name="Auto Captions", feature_name_cn="自动字幕",
                      description="长视频字幕", ability_type="video-edit", input_modality=["video"],
                      output_modality="video", complexity="hard", extraction_confidence=0.85),
    ]
    monkeypatch.setattr(fx, "_call_llm", lambda app: fx.LLMFeatureList(features=feats))
    fx._clear_cache()
    cand = {"canonical_key": "app_store:123", "name": "CapCut",
            "description": "video editor", "regions": ["US", "CN"],
            "entry_types": ["top_free"], "rating_available": True}
    specs = fx.extract_features_llm(cand)
    by_key = {"app_store:123": cand}
    ranked = rank_features(specs, by_key)
    ranked_types = {r["ability_type"] for r in ranked}
    assert "bg-remove" in ranked_types          # buildable 进 ranked
    assert "video-edit" not in ranked_types      # buildable=false 被闸门 A 挡住
    assert any(s["ability_type"] == "video-edit" for s in specs)  # 但全量产物保留(复盘)


def test_capcut_end_to_end(monkeypatch):
    """CapCut: 剪辑/字幕(buildable=false,复盘) + 背景去除(buildable+auto_publishable)
    + 头像(buildable,auto_publishable=false,标 review)。"""
    feats = [
        fx.LLMFeature(feature_name="Background Remover", feature_name_cn="背景去除",
                      description="去背景", ability_type="bg-remove", input_modality=["image"],
                      output_modality="image", complexity="easy", extraction_confidence=0.92),
        fx.LLMFeature(feature_name="AI Avatar", feature_name_cn="AI 头像",
                      description="生成头像", ability_type="avatar-gen", input_modality=["text"],
                      output_modality="image", complexity="medium", extraction_confidence=0.88),
        fx.LLMFeature(feature_name="Video Editing", feature_name_cn="视频剪辑",
                      description="时间线剪辑", ability_type="video-edit", input_modality=["video"],
                      output_modality="video", complexity="hard", extraction_confidence=0.9),
    ]
    monkeypatch.setattr(fx, "_call_llm", lambda app: fx.LLMFeatureList(features=feats))
    fx._clear_cache()
    specs = fx.extract_features_llm({"canonical_key": "app_store:123", "name": "CapCut",
                                     "description": "video editor"})
    by = {s["ability_type"]: s for s in specs}

    assert by["bg-remove"]["buildable"] and by["bg-remove"]["auto_publishable"]
    assert by["avatar-gen"]["buildable"] and not by["avatar-gen"]["auto_publishable"]
    assert not by["video-edit"]["buildable"]
    assert by["video-edit"]["unsupported_reasons"]
    # feature_key 不含 ability_type
    assert by["bg-remove"]["feature_key"] == "app_store:123:background-remover"
```

- [ ] **步骤 2：运行测试验证失败/通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction_llm.py -k "gate_a or end_to_end" -v`
预期：若任务 1-4 实现正确则 PASS；若 FAIL 按报错修实现（不是改测试）。

- [ ] **步骤 3：全量回归**

运行：`.venv/bin/python -m pytest core/opportunity -v`
预期：全部 PASS（含 classifier/crawl_runner/processed_apps 等既有测试不被破坏）

- [ ] **步骤 4：ruff 检查**

运行：`.venv/bin/python -m ruff check core/opportunity/ability_map.py core/opportunity/feature_extraction_llm.py core/opportunity/feature_extraction.py`
预期：无 error（有可自动修的 warning 用 `ruff check --fix`）

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/tests/test_feature_extraction_llm.py
git commit -m "test(opportunity): 闸门 A 回归 + CapCut 端到端(buildable 分层/feature_key 稳定)"
```

---

## 自检结果

**1. 规格覆盖度：**
- §3 FeatureSpec 契约 → 任务 2（schema）+ 任务 3（build_feature_spec 全字段）✅
- §3.1 修正 1（feature_key 不含 ability_type）→ 任务 3 `_stable_feature_key` + 测试 ✅
- §3.1 修正 2（extraction_confidence 改名）→ 任务 2 schema 字段名 ✅
- §3.2 Top-N 只约束入队 → 任务 4 `extract_features_llm` + 测试 ✅
- §4 ability_map 映射表 → 任务 1 全表 + 对齐测试 ✅
- §4.0 铁律（无 text2img 误映射）→ 任务 1 `test_iron_rule...` ✅
- §4.1 双布尔 → 任务 1 ABILITY_MAP + 任务 3 回填 ✅
- §4.2 闸门 A 接入（production_recommended=buildable&&fit）→ 任务 3 + 任务 6 回归 ✅
- §5 架构（门面/fallback/超时重试缓存）→ 任务 4+5 ✅
- §6 验证（6+2 条断言）→ 任务 1/3/4/6 测试覆盖 ✅

**2. 占位符扫描：** 无 TODO/待定；每个代码步骤含完整代码。✅

**3. 类型一致性：** `LLMFeature`/`LLMFeatureList`/`build_feature_spec`/`_stable_feature_key`/`_call_llm`/`extract_features_llm`/`_clear_cache`/`ABILITY_MAP`/`resolve`/`ABILITY_TYPES` 跨任务命名一致。`extract_all(candidates, enrich=False)` 签名与门面测试一致。✅
