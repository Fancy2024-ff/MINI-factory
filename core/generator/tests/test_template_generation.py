"""core.generator.template_generation 测试 — 全程注入 fake generate，不打真实 provider。"""

from __future__ import annotations

import pytest

from core.integrations.image_generation import ImageGenerationError
from core.generator import template_generation as tg


def _fake_ok(prompt, style="", aspect_ratio="1:1"):
    return {"image_url": None, "image_base64": "QUJD", "metadata": {"p": prompt}}


def test_supported_templates_whitelist():
    assert "ai-image" in tg.SUPPORTED_TEMPLATES
    assert "avatar-viral" in tg.SUPPORTED_TEMPLATES
    assert "sticker-viral" in tg.SUPPORTED_TEMPLATES
    assert "pet-talk-viral" in tg.SUPPORTED_TEMPLATES
    # 不应包含本轮未做的模板
    assert "funny-video-viral" not in tg.SUPPORTED_TEMPLATES
    assert "blessing-video-viral" not in tg.SUPPORTED_TEMPLATES


def test_build_avatar_prompt_includes_subject_and_style():
    p = tg.build_avatar_prompt({"prompt": "短发女生", "style": "cinematic", "mood": "cool", "scene": "city-night"})
    assert "短发女生" in p
    assert "cinematic" in p  # 风格映射片段
    assert "avatar" in p.lower()  # 头像方向锚定
    # 头像方向：半身/社交，不承诺换脸/真人
    assert "portrait" in p.lower()


def test_build_avatar_prompt_unknown_option_falls_back_to_keyword():
    p = tg.build_avatar_prompt({"prompt": "x", "style": "made-up-style"})
    assert "made-up-style" in p  # 未知风格作为关键词保留


def test_generate_template_avatar_returns_unified_structure():
    out = tg.generate_template("avatar-viral", {"prompt": "一个人", "style": "business"}, generate=_fake_ok)
    assert out["ok"] is True
    assert out["template_id"] == "avatar-viral"
    assert out["preview_type"] == "avatar"
    r = out["result"]
    assert r["title"] == "AI 头像已生成"
    assert r["image_base64"] == "QUJD"
    assert r["prompt"] == "一个人"  # 返回原始描述，非改写后的长 prompt


def test_generate_template_ai_image_passthrough():
    out = tg.generate_template("ai-image", {"prompt": "猫"}, generate=_fake_ok)
    assert out["template_id"] == "ai-image"
    assert out["preview_type"] == "image"


def test_generate_template_unsupported_raises():
    with pytest.raises(ImageGenerationError) as ei:
        tg.generate_template("funny-video-viral", {"prompt": "x"}, generate=_fake_ok)
    assert ei.value.code == "UNSUPPORTED_TEMPLATE"


# --- sticker-viral ---------------------------------------------------------

def test_build_sticker_prompt_includes_theme_and_mood():
    p = tg.build_sticker_prompt({"prompt": "打工人", "mood": "搞笑"})
    assert "打工人" in p
    assert "sticker" in p.lower()  # 表情包方向锚定
    assert "funny" in p.lower()    # 情绪映射片段


def test_build_sticker_prompt_is_single_clean_sticker():
    # 改为单张干净贴纸：强调单个、白底、无网格无边框，避免切图错位。
    p = tg.build_sticker_prompt({"prompt": "猫猫"}).lower()
    assert "single" in p
    assert "white background" in p
    assert "no grid" in p and "no border" in p


def test_build_sticker_prompt_uses_expression_for_set():
    # 做整套时每张指定不同表情动作。
    p = tg.build_sticker_prompt({"prompt": "猫猫", "expression": "angry grumpy expression"})
    assert "angry grumpy expression" in p


def test_generate_template_sticker_returns_unified_structure():
    out = tg.generate_template("sticker-viral", {"prompt": "猫猫", "mood": "可爱"}, generate=_fake_ok)
    assert out["ok"] is True
    assert out["template_id"] == "sticker-viral"
    assert out["preview_type"] == "stickerPack"
    r = out["result"]
    assert r["title"] == "表情包已生成"
    assert r["image_base64"] == "QUJD"
    assert r["prompt"] == "猫猫"


# --- pet-talk-viral --------------------------------------------------------

def test_build_pet_talk_prompt_includes_line():
    p = tg.build_pet_talk_prompt({"prompt": "主人该喂饭啦"})
    assert "主人该喂饭啦" in p
    assert "pet" in p.lower()


def test_generate_template_pet_talk_marks_video_unsupported():
    """诚实边界：pet-talk 核心链路跑通，产出预览/封面（real_generation=True），
    但 video_supported=False（非动态视频），标题不得宣称完整视频已生成。"""
    out = tg.generate_template("pet-talk-viral", {"prompt": "你好呀"}, generate=_fake_ok)
    assert out["ok"] is True
    assert out["template_id"] == "pet-talk-viral"
    assert out["preview_type"] == "petVideo"
    assert out["video_supported"] is False  # 非动态视频
    assert out["real_generation"] is True   # 核心链路真跑通
    assert out["fallback_mode"] is False
    # 文案：预览/封面已生成，但不得宣称完整视频已生成
    assert "预览" in out["result"]["title"]
    assert "完整视频" not in out["result"]["title"]
    assert out["result"]["prompt"] == "你好呀"


def test_generate_template_core_returns_capability_markers():
    """三个核心模板返回必须带 real_generation=True / fallback_mode=False / boundary_note。"""
    for tpl, ptype in (("avatar-viral", "avatar"), ("sticker-viral", "stickerPack"),
                       ("pet-talk-viral", "petVideo")):
        out = tg.generate_template(tpl, {"prompt": "x"}, generate=_fake_ok)
        assert out["preview_type"] == ptype
        assert out["real_generation"] is True, tpl
        assert out["fallback_mode"] is False, tpl
        assert out["boundary_note"], f"{tpl} 缺 boundary_note"


def test_generate_template_missing_prompt_raises():
    with pytest.raises(ImageGenerationError) as ei:
        tg.generate_template("avatar-viral", {"prompt": "   "}, generate=_fake_ok)
    assert ei.value.code == "VALIDATION_ERROR"


def test_generate_template_too_long_raises():
    long = "猫" * (tg.MAX_PROMPT_LEN + 1)
    with pytest.raises(ImageGenerationError) as ei:
        tg.generate_template("avatar-viral", {"prompt": long}, generate=_fake_ok)
    assert ei.value.code == "VALIDATION_ERROR"


def test_generate_template_propagates_provider_error():
    def fail(prompt, **kw):
        raise ImageGenerationError("IMAGE_GENERATION_PROVIDER_FAILED", "safe message")

    with pytest.raises(ImageGenerationError) as ei:
        tg.generate_template("avatar-viral", {"prompt": "x"}, generate=fail)
    assert ei.value.code == "IMAGE_GENERATION_PROVIDER_FAILED"
