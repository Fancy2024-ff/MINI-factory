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
    # 不应包含本轮未做的模板
    assert "sticker-viral" not in tg.SUPPORTED_TEMPLATES
    assert "funny-video-viral" not in tg.SUPPORTED_TEMPLATES


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
        tg.generate_template("sticker-viral", {"prompt": "x"}, generate=_fake_ok)
    assert ei.value.code == "UNSUPPORTED_TEMPLATE"


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
