"""core.qa.generator_qa 回归测试。

覆盖：
  - 完整模板配置通过（5 个 viral template.json + 生成产物）
  - 缺 input_fields 失败
  - preview_type 不支持失败
  - 缺 share_hooks / unlock_hooks / mock_examples 失败
  - 生成产物级：缺 blueprint.json / 残留 token / generation.ts 非 blueprint 驱动 失败
"""

import json
from pathlib import Path

import pytest

from core.qa.generator_qa import run_generator_qa


def test_full_config_passes():
    """仓库内 5 套 viral + ai-image 配置应通过配置级 + overlay 文案级检查。"""
    result = run_generator_qa()
    assert result["passed"], result["issues"]
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral", "ai-image"):
        assert result["checks"][f"template_config:{t}"] is True
        assert result["checks"][f"overlay_copy:{t}"] is True


def test_ai_image_is_in_qa_scope():
    """P0-1 收口范围必须含 ai-image：checks 里能看到它的 template_config / overlay_copy。"""
    from core.qa.generator_qa import CLASSIFIED_TEMPLATES
    assert "ai-image" in CLASSIFIED_TEMPLATES
    result = run_generator_qa()
    assert "template_config:ai-image" in result["checks"]
    assert "overlay_copy:ai-image" in result["checks"]
    # 扫描范围 = 5 套 viral + ai-image，共 6 个模板，各有两个 check 维度。
    scanned = sorted(k.split(":", 1)[1] for k in result["checks"] if k.startswith("template_config:"))
    assert scanned == sorted(["avatar-viral", "sticker-viral", "pet-talk-viral",
                              "funny-video-viral", "blessing-video-viral", "ai-image"])


def _patch_templates(monkeypatch, tmp_path):
    """把 generator_qa + blueprint_builder 的 TEMPLATES_DIR 指到临时目录。"""
    import core.qa.generator_qa as gq
    import core.generator.blueprint_builder as bb
    monkeypatch.setattr(gq, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(bb, "TEMPLATES_DIR", tmp_path)


def _write_cfg(tmp_path: Path, template: str, cfg: dict):
    d = tmp_path / template
    d.mkdir(parents=True, exist_ok=True)
    (d / "template.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def _good_cfg(template="avatar-viral"):
    # 默认按核心模板填能力字段；honest_preview 类用 _honest_cfg。
    honest = template in ("funny-video-viral", "blessing-video-viral")
    return {
        "id": template,
        "name_cn": "测试",
        "category": "viral",
        "preview_type": "avatar",
        "template_status": "honest_preview" if honest else "core_runnable",
        "status_label": "诚实预览" if honest else "核心可跑通",
        "generation_backend": "honest_fallback" if honest else "template_api",
        "real_generation": not honest,
        "fallback_mode": honest,
        "boundary_note": "能力边界说明",
        "qa_expectation": "QA 期望说明",
        "frontend_badge": "标签",
        "input_fields": [{"id": "x", "label": "x", "type": "text", "required": False, "placeholder": "p"}],
        "share_hooks": ["a", "b"],
        "unlock_hooks": ["a", "b"],
        "mock_examples": [{"title": "t", "preview_type": "avatar", "preview_data": {},
                           "share_title": "s", "share_copy": "c", "unlock_hint": "u"}],
        # P0-2：viral 模板必须带结构化 growth_loop 事实源。
        "growth_loop": _good_growth_loop(honest),
    }


def _good_growth_loop(honest: bool) -> dict:
    return {
        "has_share_cta": True,
        "share_cta_label": "分享",
        "share_title": "s",
        "share_copy": "c",
        "has_unlock": True,
        "unlock_type": "share_to_unlock",
        "unlock_hint": "u",
        "has_watermark": True,
        "watermark_label": "水印",
        "remove_watermark_supported": True,
        "brand_exposure": True,
        "brand_label": "出品",
        "download_supported": not honest,
        "export_supported": not honest,
        "export_label": "导出",
        "capability_mode": "fallback_preview" if honest else "real",
        "capability_note": "n",
    }


def test_id_mismatch_fails(tmp_path, monkeypatch):
    """template.json id 与目录名不一致必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["id"] = "wrong-id"
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert any("目录名不一致" in i for i in result["issues"])


def test_missing_input_fields_fails(tmp_path, monkeypatch):
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["input_fields"] = []
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:avatar-viral"] is False
    assert any("input_fields" in i for i in result["issues"])


def test_unsupported_preview_type_fails(tmp_path, monkeypatch):
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["preview_type"] = "hologram"  # 不受支持
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert any("preview_type" in i for i in result["issues"])


def test_missing_share_unlock_mock_fails(tmp_path, monkeypatch):
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        cfg["share_hooks"] = []
        cfg["unlock_hooks"] = []
        cfg["mock_examples"] = []
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    issues = " ".join(result["issues"])
    assert "share_hooks" in issues
    assert "unlock_hooks" in issues
    assert "mock_examples" in issues


def test_missing_capability_fields_fails(tmp_path, monkeypatch):
    """模板缺能力字段（template_status 等）必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        cfg = _good_cfg(t)
        del cfg["template_status"]
        del cfg["real_generation"]
        _write_cfg(tmp_path, t, cfg)
    result = run_generator_qa()
    assert not result["passed"]
    assert any("能力字段" in i for i in result["issues"])


def test_pet_talk_misclassified_as_honest_preview_fails(tmp_path, monkeypatch):
    """pet-talk 被错误归为 honest_preview 必须失败（它是核心可跑通）。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    # 把 pet-talk 错标成 honest_preview
    bad = _good_cfg("pet-talk-viral")
    bad["template_status"] = "honest_preview"
    bad["generation_backend"] = "honest_fallback"
    bad["real_generation"] = False
    bad["fallback_mode"] = True
    _write_cfg(tmp_path, "pet-talk-viral", bad)
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:pet-talk-viral"] is False
    assert any("pet-talk-viral" in i and "core_runnable" in i for i in result["issues"])


def test_core_template_marked_fallback_fails(tmp_path, monkeypatch):
    """核心模板被标成 fallback（real_generation=false）必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    bad = _good_cfg("avatar-viral")
    bad["real_generation"] = False
    bad["fallback_mode"] = True
    _write_cfg(tmp_path, "avatar-viral", bad)
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:avatar-viral"] is False


def test_honest_preview_misleading_copy_fails(tmp_path, monkeypatch):
    """诚实边界型模板出现「视频已生成」类误导文案必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    bad = _good_cfg("funny-video-viral")
    bad["mock_examples"][0]["title"] = "完整视频已生成"
    _write_cfg(tmp_path, "funny-video-viral", bad)
    result = run_generator_qa()
    assert not result["passed"]
    assert any("误导文案" in i for i in result["issues"])


def test_upload_claim_without_drive_flag_fails(tmp_path, monkeypatch):
    """image 输入文案宣称「上传照片」驱动生成，但未标 drives_generation:false 必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    bad = _good_cfg("avatar-viral")
    bad["input_fields"] = [
        {"id": "photo", "label": "上传照片", "type": "image", "required": False,
         "placeholder": "点击上传一张清晰正脸照"},
    ]
    _write_cfg(tmp_path, "avatar-viral", bad)
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:avatar-viral"] is False
    assert any("上传图片驱动生成" in i for i in result["issues"])


def test_upload_placeholder_with_drive_flag_passes(tmp_path, monkeypatch):
    """同样是 image 字段，标了 drives_generation:false（诚实占位）即通过该项检查。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    okcfg = _good_cfg("avatar-viral")
    okcfg["input_fields"] = [
        {"id": "photo", "label": "参考照片（占位，暂不参与生成）", "type": "image",
         "required": False, "placeholder": "可上传占位", "drives_generation": False},
    ]
    _write_cfg(tmp_path, "avatar-viral", okcfg)
    result = run_generator_qa()
    # avatar-viral 该项不因上传文案失败（其它模板正常）。
    assert result["checks"]["template_config:avatar-viral"] is True
    assert not any("上传图片驱动生成" in i for i in result["issues"])


def test_repo_templates_have_no_upload_dishonesty():
    """仓库内真实 5+1 模板：不得存在「宣称上传驱动但未标占位」的 image 字段。"""
    result = run_generator_qa()
    assert not any("上传图片驱动生成" in i for i in result["issues"]), result["issues"]


def test_image_field_missing_drives_generation_fails(tmp_path, monkeypatch):
    """image 字段缺 drives_generation（默认视为参与生成）必须失败（上传链未接入）。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    bad = _good_cfg("avatar-viral")
    bad["input_fields"] = [
        # 中性文案（不含"上传照片"），仅靠 drives_generation 缺失就该失败。
        {"id": "photo", "label": "图片", "type": "image", "required": False, "placeholder": "选择"},
    ]
    _write_cfg(tmp_path, "avatar-viral", bad)
    result = run_generator_qa()
    assert result["checks"]["template_config:avatar-viral"] is False
    assert any("drives_generation" in i and "false" in i for i in result["issues"])


def test_image_field_drives_generation_true_fails(tmp_path, monkeypatch):
    """image 字段 drives_generation=true（声称参与生成）必须失败（无真实上传链）。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    bad = _good_cfg("avatar-viral")
    bad["input_fields"] = [
        {"id": "photo", "label": "图片", "type": "image", "required": False,
         "placeholder": "选择", "drives_generation": True},
    ]
    _write_cfg(tmp_path, "avatar-viral", bad)
    result = run_generator_qa()
    assert result["checks"]["template_config:avatar-viral"] is False
    assert any("drives_generation" in i for i in result["issues"])


def test_image_field_drives_generation_false_passes(tmp_path, monkeypatch):
    """image 字段标 drives_generation=false（占位）通过该策略检查。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    ok = _good_cfg("avatar-viral")
    ok["input_fields"] = [
        {"id": "photo", "label": "参考图（占位）", "type": "image", "required": False,
         "placeholder": "占位", "drives_generation": False},
        {"id": "style", "label": "风格", "type": "text", "required": False, "placeholder": "p"},
    ]
    _write_cfg(tmp_path, "avatar-viral", ok)
    result = run_generator_qa()
    assert result["checks"]["template_config:avatar-viral"] is True


def test_repo_image_fields_all_placeholder():
    """仓库真实模板：所有 image 字段都已标 drives_generation:false（无 drives_generation 违规）。"""
    result = run_generator_qa()
    assert not any("drives_generation" in i for i in result["issues"]), result["issues"]


# --- overlay Vue 用户可见文案诚实性（P0-1 收口）---

def _write_vue(tmp_path: Path, template: str, page: str, body: str):
    """在临时模板目录写一个 overlay 页 src/pages/<page>/<page>.vue。"""
    d = tmp_path / template / "src" / "pages" / page
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{page}.vue").write_text(body, encoding="utf-8")


def _pet_talk_cfg_with_placeholder_image():
    """pet-talk：core_runnable + petVideo + 占位 image 字段（drives_generation false）。"""
    cfg = _good_cfg("pet-talk-viral")
    cfg["preview_type"] = "petVideo"
    cfg["input_fields"] = [
        {"id": "pet_photo", "label": "宠物照片（占位）", "type": "image", "required": False,
         "placeholder": "占位，可选", "drives_generation": False},
        {"id": "line", "label": "台词", "type": "textarea", "required": True, "placeholder": "说点啥"},
    ]
    return cfg


def test_overlay_vue_video_claim_fails(tmp_path, monkeypatch):
    """pet-talk（core_runnable 但非动态视频）页面出现「生成视频」文案必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    _write_cfg(tmp_path, "pet-talk-viral", _pet_talk_cfg_with_placeholder_image())
    _write_vue(tmp_path, "pet-talk-viral", "index",
               "<template><view><button>生成视频分享朋友圈</button></view></template>")
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:pet-talk-viral"] is False
    assert any("视频误导文案" in i for i in result["issues"])


def test_overlay_vue_upload_cta_fails(tmp_path, monkeypatch):
    """image 字段仅占位时，页面 CTA「上传照片，生成」必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    avatar = _good_cfg("avatar-viral")
    avatar["input_fields"] = [
        {"id": "photo", "label": "参考照片（占位）", "type": "image", "required": False,
         "placeholder": "占位", "drives_generation": False},
    ]
    _write_cfg(tmp_path, "avatar-viral", avatar)
    _write_vue(tmp_path, "avatar-viral", "index",
               "<template><view><button>上传照片，生成头像</button></view></template>")
    result = run_generator_qa()
    assert not result["passed"]
    assert result["checks"]["template_config:avatar-viral"] is False
    assert any("上传图片驱动生成" in i for i in result["issues"])


def test_overlay_vue_bare_upload_without_qualifier_fails(tmp_path, monkeypatch):
    """非 CTA 文本节点裸「上传照片」且【同段】无占位修饰必须失败。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    avatar = _good_cfg("avatar-viral")
    avatar["input_fields"] = [
        {"id": "photo", "label": "参考照片（占位）", "type": "image", "required": False,
         "placeholder": "占位", "drives_generation": False},
    ]
    _write_cfg(tmp_path, "avatar-viral", avatar)
    _write_vue(tmp_path, "avatar-viral", "index",
               "<template><view><text>上传照片</text></view></template>")
    result = run_generator_qa()
    assert result["checks"]["overlay_copy:avatar-viral"] is False
    assert any("缺少占位说明" in i for i in result["issues"])


def test_overlay_vue_placeholder_attr_misleading_fails(tmp_path, monkeypatch):
    """placeholder 属性出现「上传图片处理」（上传驱动短语）必须被拦住。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    cfg = _pet_talk_cfg_with_placeholder_image()
    _write_cfg(tmp_path, "pet-talk-viral", cfg)
    # 误导文案藏在 placeholder 属性里（旧实现去标签后会丢属性值，漏判）。
    _write_vue(tmp_path, "pet-talk-viral", "upload",
               '<template><view><input placeholder="上传图片处理" /></view></template>')
    result = run_generator_qa()
    assert result["checks"]["overlay_copy:pet-talk-viral"] is False
    assert any("上传图片驱动生成" in i for i in result["issues"])


def test_overlay_vue_aria_label_video_claim_fails(tmp_path, monkeypatch):
    """aria-label 属性里的「生成视频」也要被视频误导规则拦住。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    _write_cfg(tmp_path, "pet-talk-viral", _pet_talk_cfg_with_placeholder_image())
    _write_vue(tmp_path, "pet-talk-viral", "index",
               '<template><view><button aria-label="生成视频">开始</button></view></template>')
    result = run_generator_qa()
    assert result["checks"]["overlay_copy:pet-talk-viral"] is False
    assert any("视频误导文案" in i for i in result["issues"])


def test_overlay_vue_cta_bare_upload_banned_even_with_separate_qualifier(tmp_path, monkeypatch):
    """规则固定：CTA(button) 里裸「上传照片」一律禁，
    即便另起一段写了「占位」也不放过（主按钮文案本身在误导）。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    avatar = _good_cfg("avatar-viral")
    avatar["input_fields"] = [
        {"id": "photo", "label": "参考照片（占位）", "type": "image", "required": False,
         "placeholder": "占位", "drives_generation": False},
    ]
    _write_cfg(tmp_path, "avatar-viral", avatar)
    # 按钮裸「上传照片」+ 另一段独立「占位」说明 -> 仍必须失败。
    _write_vue(tmp_path, "avatar-viral", "index",
               "<template><view><button>上传照片</button>"
               "<text>照片仅占位，不参与生成</text></view></template>")
    result = run_generator_qa()
    assert result["checks"]["overlay_copy:avatar-viral"] is False
    assert any("行动按钮(CTA)出现" in i for i in result["issues"])


def test_overlay_vue_text_node_inline_qualifier_passes(tmp_path, monkeypatch):
    """规则固定：非 CTA 文本节点裸「上传照片」+【同段】占位修饰 -> 放过。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    avatar = _good_cfg("avatar-viral")
    avatar["input_fields"] = [
        {"id": "photo", "label": "参考照片（占位）", "type": "image", "required": False,
         "placeholder": "占位", "drives_generation": False},
    ]
    _write_cfg(tmp_path, "avatar-viral", avatar)
    # 同一文本节点内既有"上传照片"又有"占位" -> 通过。
    _write_vue(tmp_path, "avatar-viral", "index",
               "<template><view><text>上传照片（占位，可选，不参与生成）</text></view></template>")
    result = run_generator_qa()
    assert result["checks"]["overlay_copy:avatar-viral"] is True



def test_overlay_vue_honest_copy_passes(tmp_path, monkeypatch):
    """诚实文案（输入台词生成预览 + 占位说明）通过 overlay 扫描。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    _write_cfg(tmp_path, "pet-talk-viral", _pet_talk_cfg_with_placeholder_image())
    _write_vue(tmp_path, "pet-talk-viral", "index",
               "<template><view><button>输入台词，生成预览</button>"
               "<text>上传宠物照片（占位，可选）</text></view></template>")
    _write_vue(tmp_path, "pet-talk-viral", "upload",
               "<template><view><button>生成宠物说话预览</button>"
               "<text>照片仅作占位，不参与生成</text></view></template>")
    result = run_generator_qa()
    assert result["checks"]["template_config:pet-talk-viral"] is True


def test_overlay_vue_comment_not_flagged(tmp_path, monkeypatch):
    """口径说明写在 HTML 注释里不应被误判（注释非用户可见文案）。"""
    _patch_templates(monkeypatch, tmp_path)
    for t in ("avatar-viral", "sticker-viral", "pet-talk-viral",
              "funny-video-viral", "blessing-video-viral"):
        _write_cfg(tmp_path, t, _good_cfg(t))
    _write_cfg(tmp_path, "pet-talk-viral", _pet_talk_cfg_with_placeholder_image())
    _write_vue(tmp_path, "pet-talk-viral", "index",
               "<!-- 文案不得宣称生成视频/高清视频 -->\n"
               "<template><view><button>输入台词，生成预览</button></view></template>")
    result = run_generator_qa()
    assert result["checks"]["template_config:pet-talk-viral"] is True


def test_repo_overlay_pages_no_video_or_upload_dishonesty():
    """仓库内真实 overlay 页：无视频误导 / 无占位图上传驱动 CTA 的不一致。"""
    result = run_generator_qa()
    bad = [i for i in result["issues"]
           if ("视频误导文案" in i) or ("上传图片驱动生成" in i) or ("无占位说明" in i)]
    assert not bad, bad


def _make_generated_project(miniapp_dir: Path, *, with_blueprint=True,
                            blueprint_driven=True, token_residue=False,
                            with_input_fields=False, form_consumes_blueprint=True):
    src = miniapp_dir / "src"
    (src / "config").mkdir(parents=True, exist_ok=True)
    (src / "services").mkdir(parents=True, exist_ok=True)
    if with_blueprint:
        bp = {"template_id": "avatar-viral", "preview_type": "avatar",
              "template_status": "core_runnable", "status_label": "核心可跑通",
              "generation_backend": "template_api", "real_generation": True,
              "fallback_mode": False, "result_identity": "头像",
              "boundary_note": "边界", "qa_expectation": "qa", "frontend_badge": "badge"}
        if with_input_fields:
            bp["input_fields"] = [
                {"id": "style", "label": "风格", "type": "text", "required": False, "placeholder": "p"},
            ]
        (src / "config" / "blueprint.json").write_text(
            json.dumps(bp), encoding="utf-8",
        )
    svc = "export function mockGenerate(){}"
    if blueprint_driven:
        svc = "export const GENERATION_MODE = 'mock'\nexport const IMAGE_GENERATION_PATH = '/api/generation/image'\nasync function callRealApi(){}\nexport function loadBlueprint(){}\nexport function generateFromBlueprint(){}\n" + svc
    (src / "services" / "generation.ts").write_text(svc, encoding="utf-8")
    # form.vue：可选 blueprint-driven。
    (src / "pages" / "form").mkdir(parents=True, exist_ok=True)
    if form_consumes_blueprint:
        form = ("<template><view></view></template>\n<script setup>\n"
                "import { loadBlueprint } from '../../services/generation'\n"
                "const bp = loadBlueprint(); const fields = bp.input_fields\n"
                "const extra = {}\n</script>")
    else:
        form = "<template><textarea /></template>\n<script setup>const x=1</script>"
    (src / "pages" / "form" / "form.vue").write_text(form, encoding="utf-8")
    if token_residue:
        (src / "config" / "leak.ts").write_text("export const X = '__APP_TEMPLATE__'", encoding="utf-8")


def test_generated_form_blueprint_driven_passes(tmp_path):
    """blueprint 有 input_fields + form 消费它 -> form_blueprint_driven 通过。"""
    mini = tmp_path / "mini"
    _make_generated_project(mini, with_input_fields=True, form_consumes_blueprint=True)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["form_blueprint_driven"] is True


def test_generated_form_ignores_blueprint_fields_fails(tmp_path):
    """blueprint 有 input_fields 但 form 不消费 -> 必须失败。"""
    mini = tmp_path / "mini"
    _make_generated_project(mini, with_input_fields=True, form_consumes_blueprint=False)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["form_blueprint_driven"] is False
    assert not result["passed"]
    assert any("未消费 blueprint.input_fields" in i for i in result["issues"])





def test_generated_project_passes(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_blueprint_exists"] is True
    assert result["checks"]["generated_blueprint_capability_fields"] is True
    assert result["checks"]["generated_no_token_residue"] is True
    assert result["checks"]["generation_blueprint_driven"] is True
    assert result["checks"]["generation_api_mode_path"] is True
    assert result["checks"]["generated_no_provider_secret_residue"] is True


def test_generated_blueprint_missing_capability_fields_fails(tmp_path):
    """生成项目 blueprint.json 缺能力字段必须失败。"""
    mini = tmp_path / "mini"
    _make_generated_project(mini)
    # 覆写成缺能力字段的 blueprint
    (mini / "src" / "config" / "blueprint.json").write_text(
        json.dumps({"template_id": "avatar-viral", "preview_type": "avatar"}),
        encoding="utf-8",
    )
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_blueprint_capability_fields"] is False
    assert not result["passed"]


def test_generated_missing_blueprint_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini, with_blueprint=False)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_blueprint_exists"] is False
    assert not result["passed"]


def test_generated_token_residue_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini, token_residue=True)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_no_token_residue"] is False
    assert not result["passed"]


def test_generated_not_blueprint_driven_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini, blueprint_driven=False)
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generation_blueprint_driven"] is False
    assert not result["passed"]


def test_generated_provider_secret_residue_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini)
    (mini / "src" / "config" / "bad.ts").write_text(
        "export const BAD = 'IMAGE_GENERATION_API_KEY'",
        encoding="utf-8",
    )
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generated_no_provider_secret_residue"] is False
    assert not result["passed"]


def test_generated_missing_api_mode_fails(tmp_path):
    mini = tmp_path / "mini"
    _make_generated_project(mini)
    svc = "export function loadBlueprint(){}\nexport function generateFromBlueprint(){}\nexport function mockGenerate(){}"
    (mini / "src" / "services" / "generation.ts").write_text(svc, encoding="utf-8")
    result = run_generator_qa(miniapp_dir=mini)
    assert result["checks"]["generation_api_mode_path"] is False
    assert not result["passed"]
