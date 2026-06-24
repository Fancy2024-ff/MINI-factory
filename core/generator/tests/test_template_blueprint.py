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


# --- 传播闭环 growth_loop（P0-2）---

GROWTH_LOOP_KEYS = (
    "has_share_cta", "share_cta_label", "share_title", "share_copy",
    "has_unlock", "unlock_type", "unlock_hint",
    "has_watermark", "watermark_label", "remove_watermark_supported",
    "brand_exposure", "brand_label",
    "download_supported", "export_supported", "export_label",
    "capability_mode", "capability_note",
)


@pytest.mark.parametrize("template", VIRAL)
def test_viral_template_has_growth_loop(template):
    """5 个 viral 模板 template.json 都必须带结构化 growth_loop。"""
    cfg = load_template_config(template)
    assert "growth_loop" in cfg, f"{template} 缺少 growth_loop"
    gl = cfg["growth_loop"]
    for k in GROWTH_LOOP_KEYS:
        assert k in gl, f"{template} growth_loop 缺键 {k}"


@pytest.mark.parametrize("template", VIRAL)
def test_blueprint_carries_growth_loop(template):
    """build_template_blueprint 返回值必须含完整 growth_loop。"""
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    assert "growth_loop" in bp
    for k in GROWTH_LOOP_KEYS:
        assert k in bp["growth_loop"], f"{template} blueprint.growth_loop 缺键 {k}"


@pytest.mark.parametrize("template", CORE_RUNNABLE)
def test_core_growth_loop_capability_real(template):
    """核心模板 growth_loop.capability_mode 必须为 real。"""
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    assert bp["growth_loop"]["capability_mode"] == "real"
    assert bp["growth_loop"]["export_supported"] is True


@pytest.mark.parametrize("template", HONEST_PREVIEW)
def test_video_growth_loop_capability_fallback_preview(template):
    """funny/blessing growth_loop.capability_mode 必须为 fallback_preview（不冒充真实视频）。"""
    bp = build_template_blueprint(template, SAMPLE_APP, SAMPLE_PRD)
    assert bp["growth_loop"]["capability_mode"] == "fallback_preview"
    note = bp["growth_loop"]["capability_note"]
    assert "preview" in note.lower() or "预览" in note


def test_core_growth_loops_are_differentiated():
    """三个核心模板的传播闭环必须与题材匹配、互不相同（不是同一套通用文案壳）。"""
    avatar = build_template_blueprint("avatar-viral", SAMPLE_APP, SAMPLE_PRD)["growth_loop"]
    sticker = build_template_blueprint("sticker-viral", SAMPLE_APP, SAMPLE_PRD)["growth_loop"]
    pet = build_template_blueprint("pet-talk-viral", SAMPLE_APP, SAMPLE_PRD)["growth_loop"]

    # 分享 CTA 文案各不相同
    labels = {avatar["share_cta_label"], sticker["share_cta_label"], pet["share_cta_label"]}
    assert len(labels) == 3, f"核心模板 share_cta_label 应各不相同: {labels}"

    # unlock_type 与题材匹配
    assert avatar["unlock_type"] == "share_to_unlock"
    assert sticker["unlock_type"] == "group_share_unlock"
    assert pet["unlock_type"] == "timeline_share_unlock"

    # 题材关键词出现在文案里
    assert "头像" in avatar["share_title"]
    assert "表情" in sticker["share_title"] or "群" in sticker["share_copy"]
    assert "宠物" in pet["share_title"]


def test_missing_growth_loop_raises_for_viral(tmp_path, monkeypatch):
    """viral 模板缺 growth_loop 必须失败（不允许只靠 share_hooks）。"""
    import core.generator.blueprint_builder as bb
    import json as _json
    d = tmp_path / "avatar-viral"
    d.mkdir()
    # 取真实配置，删掉 growth_loop
    real = _json.loads((bb.TEMPLATES_DIR / "avatar-viral" / "template.json").read_text(encoding="utf-8-sig"))
    real.pop("growth_loop", None)
    (d / "template.json").write_text(_json.dumps(real, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(BlueprintError):
        bb.build_template_blueprint("avatar-viral", SAMPLE_APP, SAMPLE_PRD)


def test_growth_loop_capability_mismatch_raises(tmp_path, monkeypatch):
    """real_generation=true 但 growth_loop.capability_mode=fallback_preview 必须失败（口径冲突）。"""
    import core.generator.blueprint_builder as bb
    import json as _json
    d = tmp_path / "avatar-viral"
    d.mkdir()
    real = _json.loads((bb.TEMPLATES_DIR / "avatar-viral" / "template.json").read_text(encoding="utf-8-sig"))
    real["growth_loop"]["capability_mode"] = "fallback_preview"  # 与 real_generation=true 冲突
    (d / "template.json").write_text(_json.dumps(real, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(BlueprintError):
        bb.build_template_blueprint("avatar-viral", SAMPLE_APP, SAMPLE_PRD)


def test_growth_loop_for_template_helper():
    """growth_loop_for_template 供 growth 文档消费：viral 取事实源，未知模板回退通用。"""
    from core.generator.blueprint_builder import growth_loop_for_template
    gl = growth_loop_for_template("sticker-viral")
    assert gl["capability_mode"] == "real"
    assert gl["unlock_type"] == "group_share_unlock"
    # 未知/兜底模板：通用 growth_loop，不报错
    generic = growth_loop_for_template("ai-tool")
    assert generic["capability_mode"] in ("real", "fallback_preview")
    assert "has_share_cta" in generic


# --- finding #4：growth_loop_for_template 对 viral 模板不得吞错 ---


def test_growth_loop_for_template_reraises_for_broken_viral(tmp_path, monkeypatch):
    """viral 模板缺 growth_loop 时，growth_loop_for_template 必须抛 BlueprintError（不静默降级）。"""
    import core.generator.blueprint_builder as bb
    from core.generator.blueprint_builder import growth_loop_for_template
    d = tmp_path / "avatar-viral"
    d.mkdir()
    real = json.loads((bb.TEMPLATES_DIR / "avatar-viral" / "template.json").read_text(encoding="utf-8-sig"))
    real.pop("growth_loop", None)
    (d / "template.json").write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(BlueprintError):
        growth_loop_for_template("avatar-viral")


def test_growth_loop_for_template_reraises_on_capability_mismatch(tmp_path, monkeypatch):
    """viral 模板 capability_mode 与 real_generation 冲突时也必须抛错。"""
    import core.generator.blueprint_builder as bb
    from core.generator.blueprint_builder import growth_loop_for_template
    d = tmp_path / "avatar-viral"
    d.mkdir()
    real = json.loads((bb.TEMPLATES_DIR / "avatar-viral" / "template.json").read_text(encoding="utf-8-sig"))
    real["growth_loop"]["capability_mode"] = "fallback_preview"  # 与 real_generation=true 冲突
    (d / "template.json").write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(BlueprintError):
        growth_loop_for_template("avatar-viral")


def test_growth_loop_for_template_unknown_nonviral_falls_back(tmp_path, monkeypatch):
    """非 viral 未知模板缺配置时仍回退通用 growth_loop（不抛错）。"""
    import core.generator.blueprint_builder as bb
    from core.generator.blueprint_builder import growth_loop_for_template
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)
    gl = growth_loop_for_template("totally-unknown-tool")
    assert gl["capability_mode"] in ("real", "fallback_preview")
    assert "has_share_cta" in gl
