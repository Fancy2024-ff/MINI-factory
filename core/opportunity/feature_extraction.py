"""core.opportunity.feature_extraction — 大 App 功能拆解为小程序机会。

把一个 AppCandidate 拆成多个 FeatureOpportunity：很多热门 App（如剪映/CapCut）
太重，不能整体小程序化，但其中某些轻量功能（AI 修图/背景去除/头像/封面）适合
独立做成小程序。不能做的功能也记录 unsupported_reasons，不丢弃。

第一版规则驱动：按 name/description/features 文本匹配功能类型，映射到模板。
"""

from __future__ import annotations

from core.opportunity.ability_map import AUTO_PUBLISHABLE_TEMPLATES

# (feature_key_suffix, 名称, 中文名, 关键词, 模板, 所需能力, 难度, 基础fit, 基础viral)
_DOABLE_FEATURES = [
    ("ai_photo_retouch", "AI photo retouch", "AI 修图",
     ["retouch", "修图", "美颜", "enhance face", "beautify"],
     "ai-image", ["image_generation", "image_enhancement"], "medium", 86, 78),
    ("background_remover", "Background remover", "背景去除",
     ["background remover", "remove background", "抠图", "背景去除", "cutout"],
     "background-remover", ["image_generation"], "easy", 88, 72),
    ("watermark_remover", "Watermark remover", "去水印",
     ["watermark", "remove watermark", "去水印", "水印", "去除水印", "watermark remover"],
     "watermark-remover", ["image_generation"], "easy", 87, 74),
    ("photo_enhancer", "Photo enhancer", "图片增强",
     ["enhancer", "增强", "high resolution", "old photo", "老照片", "修复", "upscale"],
     "ai-image", ["image_generation", "image_enhancement"], "medium", 84, 70),
    ("avatar", "AI avatar", "AI 头像",
     ["avatar", "头像", "portrait", "写真", "profile pic"],
     "avatar-viral", ["image_generation"], "medium", 88, 82),
    ("sticker", "Sticker maker", "表情包",
     ["sticker", "表情", "emoji", "贴纸"],
     "sticker-viral", ["image_generation"], "easy", 82, 84),
    ("meme", "Meme generator", "梗图",
     ["meme", "梗图", "搞笑图"],
     "sticker-viral", ["image_generation"], "easy", 80, 83),
    ("pet_talk", "Pet talk", "宠物说话",
     ["pet talk", "宠物说话", "talking pet", "宠物配音"],
     "pet-talk-viral", ["image_generation"], "medium", 78, 80),
    ("blessing", "Blessing card", "祝福视频/贺卡",
     ["blessing", "祝福", "greeting card", "新年", "节日贺卡"],
     "blessing-video-viral", ["image_generation"], "medium", 76, 79),
    ("cover_maker", "Cover maker", "封面图",
     ["cover maker", "封面", "thumbnail"],
     "ai-image", ["image_generation"], "easy", 80, 68),
    ("poster_maker", "Poster maker", "海报生成",
     ["poster", "海报"],
     "ai-image", ["image_generation"], "medium", 78, 67),
    ("writing", "Writing assistant", "文案生成",
     ["writing", "文案", "copywriting", "write"],
     "ai-tool", ["llm"], "easy", 74, 60),
    ("translate", "Translate", "翻译",
     ["translate", "翻译", "translator"],
     "ai-tool", ["llm"], "easy", 72, 55),
    ("summarize", "Summarize", "摘要",
     ["summarize", "摘要", "summary"],
     "ai-tool", ["llm"], "easy", 70, 54),
]

# 第一阶段不推荐/降权的重功能：(名称, 中文名, 关键词, 难度, 低fit, unsupported 原因)
_HARD_FEATURES = [
    ("AI subtitles for long video", "长视频 AI 字幕",
     ["subtitle", "字幕", "caption"],
     "hard", 35, ["长视频处理成本高", "小程序端上传/转码体验重", "第一阶段缺少稳定视频处理 provider"]),
    ("Long video editing", "长视频剪辑",
     ["video editor", "视频剪辑", "timeline", "剪辑器", "video editing"],
     "hard", 30, ["完整视频编辑器太重", "不适合即用即走小程序", "依赖复杂时间线/转码"]),
    ("Real-time camera", "实时相机",
     ["real-time camera", "实时相机", "live camera", "ar camera"],
     "hard", 28, ["实时相机/AR 依赖原生能力", "小程序端难以稳定支持"]),
    ("AR / 3D", "AR/3D",
     ["ar ", "3d ", "augmented reality"],
     "hard", 25, ["AR/3D 渲染重", "第一阶段不做"]),
]


def _text(candidate: dict) -> str:
    parts = [
        candidate.get("name", ""), candidate.get("name_cn", ""),
        candidate.get("description", ""),
        " ".join(candidate.get("categories", []) or []),
        " ".join(candidate.get("keywords", []) or []),
        " ".join(candidate.get("features", []) or []),
    ]
    return " ".join(parts).lower()


def _difficulty_factor(diff: str) -> int:
    return {"easy": 90, "medium": 75, "hard": 45}.get(diff, 70)


def extract_features(candidate: dict) -> list[dict]:
    """从候选 App 拆出 FeatureOpportunity 列表（含可做 + 暂不推荐）。"""
    text = _text(candidate)
    parent_key = candidate.get("canonical_key", "")
    parent_name = candidate.get("name", "")
    out: list[dict] = []

    for suffix, name, name_cn, kws, template, caps, diff, base_fit, base_viral in _DOABLE_FEATURES:
        if not any(kw in text for kw in kws):
            continue
        reason = [
            "功能轻量，适合即用即走",
            "原 App 热度高，需求已验证" if candidate.get("appear_count", 0) >= 2 else "需求来自热门 App",
            "结果适合分享传播" if base_viral >= 70 else "可独立成单一能力",
            "比完整 App 更适合小程序化",
        ]
        out.append({
            "feature_key": f"{parent_key}:{suffix}",
            "parent_app_key": parent_key,
            "parent_app_name": parent_name,
            "feature_name": name,
            "feature_name_cn": name_cn,
            "description": f"从 {parent_name} 中拆出的轻量能力：{name_cn}",
            "miniapp_fit_score": base_fit,
            "implementation_difficulty": diff,
            "implementation_score": _difficulty_factor(diff),
            "required_capabilities": caps,
            "unsupported_reasons": [],
            "selected_template": template,
            "auto_publishable": template in AUTO_PUBLISHABLE_TEMPLATES,
            "data_source": "rule_fallback",
            "viral_score": base_viral,
            "production_recommended": True,
            "reason": reason,
        })

    for name, name_cn, kws, diff, low_fit, reasons in _HARD_FEATURES:
        if not any(kw in text for kw in kws):
            continue
        suffix = name_cn  # 仅作记录用 key
        out.append({
            "feature_key": f"{parent_key}:hard:{_slug(name)}",
            "parent_app_key": parent_key,
            "parent_app_name": parent_name,
            "feature_name": name,
            "feature_name_cn": name_cn,
            "description": f"{parent_name} 的重功能：{name_cn}（第一阶段暂不推荐）",
            "miniapp_fit_score": low_fit,
            "implementation_difficulty": diff,
            "implementation_score": _difficulty_factor(diff),
            "required_capabilities": [],
            "unsupported_reasons": reasons,
            "selected_template": "",
            "auto_publishable": False,
            "data_source": "rule_fallback",
            "viral_score": 0,
            "production_recommended": False,
            "reason": ["原 App 含该功能，但不适合第一阶段小程序化"],
        })

    return out


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


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
