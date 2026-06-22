"""core.generator.template_generation — 模板级生成 adapter（capability-domain）。

职责：把「模板 + 用户结构化输入」转成适合该题材的生成调用，统一返回结构。
底层唯一 provider 真源 = core.integrations.image_generation.generate_image。

设计：
- 每个模板有自己的 prompt adapter（把社交输入转成高质量出图 prompt），
  业务前端不直接拼复杂 prompt。
- 统一返回 {ok, template_id, preview_type, result{...}} 或抛 ImageGenerationError。
- 白名单：目前只 ai-image + avatar-viral；新增模板在此登记。
"""

from __future__ import annotations

from typing import Any, Callable

from core.integrations import image_generation
from core.integrations.image_generation import ImageGenerationError

# 公开模板白名单（runtime endpoint 也据此校验）。
SUPPORTED_TEMPLATES = ("ai-image", "avatar-viral")

MAX_PROMPT_LEN = 2000

# 头像风格 / 气质 / 场景 -> 出图提示词片段。未知值原样作为关键词，保证可扩展。
_AVATAR_STYLE = {
    "cinematic": "cinematic portrait, film still, dramatic lighting",
    "cyberpunk": "cyberpunk style, neon rim light, futuristic",
    "jp-photo": "Japanese photo studio style, soft natural tones",
    "business": "professional business headshot, clean studio look",
    "guofeng": "Chinese traditional guofeng aesthetic, elegant",
    "3d-cartoon": "stylized 3D cartoon avatar, Pixar-like render",
}
_AVATAR_MOOD = {
    "cool": "cool and aloof expression",
    "sunny": "warm sunny smile",
    "fierce": "confident edgy attitude",
    "gentle": "gentle soft expression",
    "professional": "composed professional demeanor",
}
_AVATAR_SCENE = {
    "solid": "clean solid color background",
    "city-night": "blurred city night bokeh background",
    "natural-light": "soft natural daylight background",
    "future-tech": "subtle futuristic tech background",
}


def _opt(table: dict[str, str], key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    return table.get(key, key)


def build_avatar_prompt(inp: dict[str, Any]) -> str:
    """把人物描述 + 风格/气质/场景合成头像出图 prompt。

    方向：社交头像 / 半身肖像 / 干净背景 / 高级质感 / 明确风格；
    不夸大、不承诺换脸/真人写真。
    """
    subject = (inp.get("prompt") or "").strip()
    parts = [
        "high quality social media avatar",
        "upper-body portrait",
        subject,
        _opt(_AVATAR_STYLE, inp.get("style", "")),
        _opt(_AVATAR_MOOD, inp.get("mood", "")),
        _opt(_AVATAR_SCENE, inp.get("scene", "")),
        "refined premium texture, sharp focus, tasteful composition",
    ]
    return ", ".join(p for p in parts if p)


def _avatar_caption(inp: dict[str, Any]) -> str:
    bits = []
    for k in ("style", "mood", "scene"):
        v = (inp.get(k) or "").strip()
        if v:
            bits.append(v)
    base = (inp.get("prompt") or "").strip()
    suffix = ("·".join(bits)) if bits else ""
    return f"{base}（{suffix}）" if suffix else base


def generate_template(
    template_id: str,
    inp: dict[str, Any],
    *,
    generate: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """模板级生成统一入口。generate 可注入便于测试。

    返回统一结构；校验/provider 失败抛 ImageGenerationError（由 endpoint 转结构化）。
    默认在调用时解析 image_generation.generate_image（而非定义时绑定），
    使后端 monkeypatch provider 生效。
    """
    if generate is None:
        generate = image_generation.generate_image
    if template_id not in SUPPORTED_TEMPLATES:
        raise ImageGenerationError("UNSUPPORTED_TEMPLATE", f"暂不支持模板 {template_id}")

    raw_prompt = (inp.get("prompt") or "").strip()
    if not raw_prompt:
        raise ImageGenerationError("VALIDATION_ERROR", "prompt 不能为空")
    if len(raw_prompt) > MAX_PROMPT_LEN:
        raise ImageGenerationError("VALIDATION_ERROR", f"prompt 过长（上限 {MAX_PROMPT_LEN} 字符）")

    aspect_ratio = (inp.get("aspect_ratio") or "1:1").strip() or "1:1"

    if template_id == "avatar-viral":
        final_prompt = build_avatar_prompt(inp)
        result = generate(final_prompt, style=(inp.get("style") or ""), aspect_ratio=aspect_ratio)
        return {
            "ok": True,
            "template_id": "avatar-viral",
            "preview_type": "avatar",
            "result": {
                "image_url": result.get("image_url"),
                "image_base64": result.get("image_base64"),
                "title": "AI 头像已生成",
                "caption": _avatar_caption(inp),
                "prompt": raw_prompt,
                "metadata": result.get("metadata", {}),
            },
        }

    # ai-image：直出，不加题材改写。
    result = generate(raw_prompt, style=(inp.get("style") or ""), aspect_ratio=aspect_ratio)
    return {
        "ok": True,
        "template_id": "ai-image",
        "preview_type": "image",
        "result": {
            "image_url": result.get("image_url"),
            "image_base64": result.get("image_base64"),
            "title": "AI 图片生成",
            "caption": raw_prompt[:60],
            "prompt": raw_prompt,
            "metadata": result.get("metadata", {}),
        },
    }
