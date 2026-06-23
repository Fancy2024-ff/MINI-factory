"""core.generator.blueprint_builder 回归测试。

覆盖：
  - 5 个 viral 模板 template.json 都存在
  - build_template_blueprint 对 5 个模板都成功且字段完整
  - 缺失 viral template config 会失败（不静默降级）
  - fallback 模板（ai-tool 等）可返回 fallback blueprint
"""

import json

import pytest

from core.generator.blueprint_builder import (
    SUPPORTED_PREVIEW_TYPES,
    TEMPLATES_DIR,
    VIRAL_TEMPLATES,
    BlueprintError,
    build_template_blueprint,
    load_template_config,
)

SAMPLE_APP = {"name": "Demo App", "name_cn": "演示应用", "description_cn": "传播型模板蓝图测试。"}
SAMPLE_PRD = {"target_platforms": ["wechat"]}

VIRAL = sorted(VIRAL_TEMPLATES)

BLUEPRINT_FIELDS = (
    "template_id", "app_name", "preview_type", "input_fields", "pages",
    "result_contract", "share_hooks", "unlock_hooks", "growth_angles",
    "compliance_notes", "mock_examples", "source_template_config", "is_fallback",
)


@pytest.mark.parametrize("template", VIRAL)
def test_viral_template_json_exists(template):
    cfg_path = TEMPLATES_DIR / template / "template.json"
    assert cfg_path.exists(), f"缺少 {template}/template.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    assert cfg["id"] == template


@pytest.mark.parametrize("template", VIRAL)
def test_build_blueprint_succeeds_for_viral(template):
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    assert bp["template_id"] == template
    assert bp["is_fallback"] is False
    assert bp["preview_type"] in SUPPORTED_PREVIEW_TYPES
    assert bp["input_fields"], "input_fields 不能为空"
    assert len(bp["share_hooks"]) >= 2
    assert len(bp["unlock_hooks"]) >= 2
    assert bp["mock_examples"], "mock_examples 不能为空"


@pytest.mark.parametrize("template", VIRAL)
def test_blueprint_fields_complete(template):
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    for field in BLUEPRINT_FIELDS:
        assert field in bp, f"{template} blueprint 缺字段 {field}"


def test_missing_viral_config_raises(tmp_path, monkeypatch):
    """viral 模板缺 template.json 必须失败，不静默降级。"""
    import core.generator.blueprint_builder as bb
    # 指向一个空临时模板目录，模拟 viral 模板配置缺失
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(BlueprintError):
        bb.build_template_blueprint("avatar-viral", SAMPLE_APP, SAMPLE_PRD)


def test_fallback_template_returns_fallback_blueprint(tmp_path, monkeypatch):
    """ai-tool 等兜底模板缺配置时返回 fallback blueprint（不报错）。"""
    import core.generator.blueprint_builder as bb
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    bp = bb.build_template_blueprint("ai-tool", SAMPLE_APP, SAMPLE_PRD)
    assert bp["is_fallback"] is True
    assert bp["preview_type"] == "text"
    assert bp["template_id"] == "ai-tool"


def test_invalid_json_raises(tmp_path, monkeypatch):
    import core.generator.blueprint_builder as bb
    bad_dir = tmp_path / "avatar-viral"
    bad_dir.mkdir()
    (bad_dir / "template.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(BlueprintError):
        bb.load_template_config("avatar-viral")


# --- 模板能力分类（P0-1 收口）---

CAPABILITY_KEYS = (
    "template_status", "generation_backend", "real_generation",
    "fallback_mode", "boundary_note",
)

CORE_RUNNABLE = ("avatar-viral", "sticker-viral", "pet-talk-viral")
HONEST_PREVIEW = ("funny-video-viral", "blessing-video-viral")


@pytest.mark.parametrize("template", VIRAL)
def test_blueprint_carries_capability_fields(template):
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    for k in CAPABILITY_KEYS:
        assert k in bp, f"{template} blueprint 缺能力字段 {k}"


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_core_runnable_classification(template):
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    assert bp["template_status"] == "core_runnable"
    assert bp["generation_backend"] == "template_api"
    assert bp["real_generation"] is True
    assert bp["fallback_mode"] is False


@pytest.mark.parametrize("template", HONEST_PREVIEW)
def test_honest_preview_classification(template):
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    assert bp["template_status"] == "honest_preview"
    assert bp["generation_backend"] == "honest_fallback"
    assert bp["real_generation"] is False
    assert bp["fallback_mode"] is True
    # 边界型有自己的 template.json，blueprint_is_fallback 应为 False（不是兜底配置）
    assert bp["is_fallback"] is False
