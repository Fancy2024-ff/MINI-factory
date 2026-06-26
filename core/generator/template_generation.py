"""core.generator.template_generation — 模板级生成 adapter（capability-domain）。

职责：把「模板 + 用户结构化输入」转成适合该题材的生成调用，统一返回结构。
底层唯一 provider 真源 = core.integrations.image_generation.generate_image。

设计：
- 每个模板有自己的 prompt adapter（把社交输入转成高质量出图 prompt），
  业务前端不直接拼复杂 prompt。
- 统一返回 {ok, template_id, preview_type, real_generation, fallback_mode,
  boundary_note, result{...}} 或抛 ImageGenerationError。
- 白名单 SUPPORTED_TEMPLATES：ai-image + avatar-viral + sticker-viral + pet-talk-viral
  （核心可跑通真实链路）；funny/blessing 等诚实预览型模板不在白名单，走前端 honest fallback。
"""

from __future__ import annotations

from typing import Any, Callable

from core.integrations import image_generation
from core.integrations.image_generation import ImageGenerationError

# 公开模板白名单（runtime endpoint 也据此校验）。
SUPPORTED_TEMPLATES = ("ai-image", "avatar-viral", "sticker-viral", "pet-talk-viral")

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


# 表情包情绪 -> 出图风格片段。
_STICKER_MOOD = {
    "搞笑": "funny and humorous",
    "可爱": "cute and adorable",
    "暴躁": "grumpy and sassy",
    "治愈": "warm and healing",
}


def build_sticker_prompt(inp: dict[str, Any]) -> str:
    """把表情主题 + 情绪 + 单个表情动作合成「单张表情贴纸」出图 prompt。

    方向：单个角色、单一表情、纯白背景、居中、无边框无文字。
    一次只出一个表情（不再出网格大图再切），保证每张干净无错位。
    expression（可选）：指定这一张的具体表情动作，做整套时逐张不同。
    """
    theme = (inp.get("prompt") or inp.get("theme") or "").strip()
    mood = (inp.get("mood") or "").strip()
    expression = (inp.get("expression") or "").strip()
    parts = [
        "a single cute chibi sticker of one character",
        expression,
        theme,
        _STICKER_MOOD.get(mood, mood),
        "flat cartoon style, bold clean outline, die-cut sticker",
        "centered single subject, plain solid white background",
        "no grid, no panels, no frame, no border, no text, only one sticker",
    ]
    return ", ".join(p for p in parts if p)


# 整套表情包的默认表情动作（做 4 张时逐张取用，保证每张不同且都干净）。
STICKER_EXPRESSIONS = [
    "happy smiling expression",
    "angry grumpy expression",
    "crying sad expression",
    "love heart eyes expression",
    "laughing joyful expression",
    "surprised shocked expression",
    "sleepy tired expression",
    "cool confident expression",
    "thinking curious expression",
]


def _sticker_caption(inp: dict[str, Any]) -> str:
    theme = (inp.get("prompt") or inp.get("theme") or "").strip()
    mood = (inp.get("mood") or "").strip()
    return f"{theme}（{mood}）" if mood else theme


def build_pet_talk_prompt(inp: dict[str, Any]) -> str:
    """把宠物台词合成「会说话的宠物」视频封面图 prompt。

    重要边界：当前没有真实视频/配音生成能力，这里产出的是一张「视频封面/海报」
    静态图（宠物 + 说话气泡感），真实视频生成为流程预留。adapter 不承诺出视频。
    """
    line = (inp.get("prompt") or inp.get("line") or "").strip()
    parts = [
        "cute pet portrait, expressive talking pose, mouth open as if speaking",
        "speech-bubble friendly composition, social video poster style",
        f"saying: {line}" if line else "",
        "warm lighting, high quality, vertical poster framing",
    ]
    return ", ".join(p for p in parts if p)


def _pet_talk_caption(inp: dict[str, Any]) -> str:
    line = (inp.get("prompt") or inp.get("line") or "").strip()
    return f"台词：{line}" if line else "宠物说话"


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
            "real_generation": True,
            "fallback_mode": False,
            "boundary_note": "真实出图后端生成头像；不做真人换脸 / 证件照法律效力 / 视频头像。",
            "result": {
                "image_url": result.get("image_url"),
                "image_base64": result.get("image_base64"),
                "title": "AI 头像已生成",
                "caption": _avatar_caption(inp),
                "prompt": raw_prompt,
                "metadata": result.get("metadata", {}),
            },
        }

    if template_id == "sticker-viral":
        final_prompt = build_sticker_prompt(inp)
        result = generate(final_prompt, style=(inp.get("style") or ""), aspect_ratio=aspect_ratio)
        return {
            "ok": True,
            "template_id": "sticker-viral",
            "preview_type": "stickerPack",
            "real_generation": True,
            "fallback_mode": False,
            "boundary_note": "真实出图后端生成整套表情贴纸；不做侵权 IP 表情。",
            "result": {
                "image_url": result.get("image_url"),
                "image_base64": result.get("image_base64"),
                "title": "表情包已生成",
                "caption": _sticker_caption(inp),
                "prompt": raw_prompt,
                "metadata": result.get("metadata", {}),
            },
        }

    if template_id == "pet-talk-viral":
        # 边界：核心链路跑通，产出「会说话的宠物」预览/封面/海报（真实出图）；
        # 真实动态视频 / 配音为后续能力增强边界，不在当前产出范围。
        # 故 real_generation=True（链路真跑通）但 video_supported=False（非动态视频），
        # 文案只说「预览/封面已生成」，不说「完整视频已生成」。
        final_prompt = build_pet_talk_prompt(inp)
        result = generate(final_prompt, style=(inp.get("style") or ""), aspect_ratio=aspect_ratio)
        return {
            "ok": True,
            "template_id": "pet-talk-viral",
            "preview_type": "petVideo",
            "real_generation": True,
            "fallback_mode": False,
            "video_supported": False,  # 非动态视频：当前产出静态预览/封面/海报
            "boundary_note": "核心链路跑通，产出宠物说话预览/封面/海报；真实动态视频与配音为后续增强边界。",
            "result": {
                "image_url": result.get("image_url"),
                "image_base64": result.get("image_base64"),
                "title": "宠物说话预览已生成",
                "caption": _pet_talk_caption(inp),
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
        "real_generation": True,
        "fallback_mode": False,
        "boundary_note": "真实出图后端生成图片；不做完整视频剪辑 / 专业批量修图。",
        "result": {
            "image_url": result.get("image_url"),
            "image_base64": result.get("image_base64"),
            "title": "AI 图片生成",
            "caption": raw_prompt[:60],
            "prompt": raw_prompt,
            "metadata": result.get("metadata", {}),
        },
    }
