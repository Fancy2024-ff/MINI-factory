"""模板能力分类「漂移防线」（P0-1 收口）。

单一事实源 = 各 template.json 的 template_status / generation_backend。
本测试解析 template.json，并交叉校验三处运行时清单不漂移：
  1. 后端 core.generator.template_generation.SUPPORTED_TEMPLATES
  2. 前端生成项目 generation.ts 的 API_TEMPLATES / PREVIEW_ONLY_TEMPLATES
规则：
  - core_runnable + template_api  => 必须在后端 SUPPORTED_TEMPLATES 且在前端 API_TEMPLATES；
                                     且不得在 PREVIEW_ONLY_TEMPLATES。
  - honest_preview + honest_fallback => 必须在前端 PREVIEW_ONLY_TEMPLATES；
                                        且不得被后端支持、不得在 API_TEMPLATES。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.generator.template_generation import SUPPORTED_TEMPLATES

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "generator" / "src" / "templates"
GENERATION_TS = (
    Path(__file__).resolve().parents[2]
    / "generator" / "src" / "templates" / "base" / "src" / "services" / "generation.ts"
)

# 5 套传播型 + ai-image：分类事实源就是它们各自的 template.json。
CLASSIFIED_TEMPLATES = (
    "avatar-viral", "sticker-viral", "pet-talk-viral",
    "funny-video-viral", "blessing-video-viral", "ai-image",
)


def _load_cfg(template: str) -> dict:
    return json.loads((TEMPLATES_DIR / template / "template.json").read_text(encoding="utf-8-sig"))


def _parse_ts_array(name: str) -> list[str]:
    """从 generation.ts 解析 `const NAME = ['a', 'b', ...]` 字面量。"""
    txt = GENERATION_TS.read_text(encoding="utf-8")
    m = re.search(rf"const\s+{name}\s*=\s*\[([^\]]*)\]", txt)
    assert m, f"generation.ts 未找到 {name} 数组"
    return re.findall(r"'([^']+)'", m.group(1))


@pytest.fixture(scope="module")
def api_templates() -> list[str]:
    return _parse_ts_array("API_TEMPLATES")


@pytest.fixture(scope="module")
def preview_only_templates() -> list[str]:
    return _parse_ts_array("PREVIEW_ONLY_TEMPLATES")


@pytest.mark.parametrize("template", CLASSIFIED_TEMPLATES)
def test_classification_matches_runtime_lists(template, api_templates, preview_only_templates):
    cfg = _load_cfg(template)
    status = cfg.get("template_status")
    backend = cfg.get("generation_backend")

    if status == "core_runnable" and backend == "template_api":
        assert template in SUPPORTED_TEMPLATES, (
            f"{template} 标为 core_runnable+template_api，但不在后端 SUPPORTED_TEMPLATES"
        )
        assert template in api_templates, (
            f"{template} 标为 core_runnable+template_api，但不在前端 API_TEMPLATES"
        )
        assert template not in preview_only_templates, (
            f"{template} 是核心可跑通，却出现在前端 PREVIEW_ONLY_TEMPLATES"
        )
    elif status == "honest_preview" and backend == "honest_fallback":
        assert template in preview_only_templates, (
            f"{template} 标为 honest_preview，但不在前端 PREVIEW_ONLY_TEMPLATES"
        )
        assert template not in SUPPORTED_TEMPLATES, (
            f"{template} 是诚实边界型，不得被后端 SUPPORTED_TEMPLATES 支持"
        )
        assert template not in api_templates, (
            f"{template} 是诚实边界型，不得出现在前端 API_TEMPLATES"
        )
    else:
        pytest.fail(f"{template} 分类非法：status={status!r} backend={backend!r}")


def test_supported_templates_are_all_real(api_templates):
    """后端白名单里的题材模板（除 ai-image）必须都是 core_runnable，且与前端 API_TEMPLATES 同集合。"""
    # 后端支持集合（去掉 ai-image 后都应是 viral 核心模板）。
    backend = set(SUPPORTED_TEMPLATES)
    front = set(api_templates)
    assert backend == front, f"后端 SUPPORTED_TEMPLATES {backend} 与前端 API_TEMPLATES {front} 不一致"


def test_no_template_in_both_api_and_preview(api_templates, preview_only_templates):
    """同一模板不能既在 API_TEMPLATES 又在 PREVIEW_ONLY_TEMPLATES。"""
    overlap = set(api_templates) & set(preview_only_templates)
    assert not overlap, f"模板同时出现在 API_TEMPLATES 和 PREVIEW_ONLY_TEMPLATES: {overlap}"


def test_preview_only_templates_not_backend_supported(preview_only_templates):
    """前端 PREVIEW_ONLY_TEMPLATES（视频边界型）一律不得被后端支持。"""
    for t in preview_only_templates:
        assert t not in SUPPORTED_TEMPLATES, f"{t} 是 preview-only，却被后端 SUPPORTED_TEMPLATES 支持"
