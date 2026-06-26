"""ability_map 映射真源测试：与现有白名单对齐 + 铁律(无 text2img 误映射)。"""

from __future__ import annotations

from core.opportunity import ability_map as am
from core.opportunity.classifier import _KNOWN_TEMPLATES, template_to_ability_task
from core.publisher.feature_registry import TASK_WHITELIST


def test_buildable_templates_in_known_templates():
    """所有 buildable=true 的 selected_template 必须 ∈ classifier._KNOWN_TEMPLATES。"""
    for at, m in am.ABILITY_MAP.items():
        if m["buildable"]:
            assert m["selected_template"] in _KNOWN_TEMPLATES, f"{at} 模板不在白名单"


def test_ability_task_consistent_with_classifier():
    """buildable 项的 (ability, task) 与 classifier.template_to_ability_task 一致。"""
    for at, m in am.ABILITY_MAP.items():
        if m["buildable"]:
            ab, tk = template_to_ability_task(m["selected_template"])
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
