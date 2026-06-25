"""core.opportunity.classifier — 题材归类 + 模板类型选择。

职责：根据候选 App 的题材，判断"该做什么方向"以及"用哪个模板类型"。
产物 = template-selection.json（由 pipeline 写盘）。

模板类型与 core/generator 对齐：当前生成真源支持 base/ai-tool 骨架与
avatar / sticker / pet-talk / funny-video / blessing-video 五类传播型模板。
新增题材只需在这里新增映射 + 在 generator 注册模板，pipeline 不改。
"""

from __future__ import annotations

# 题材 -> 模板类型。template 字段是传给 generator 的模板名，必须与
# core/generator/src/templates/ 下的真实目录一致。
# 传播型题材落到对应的 *-viral 模板（已落地）；其余落到通用 ai-tool。
# funny-video / blessing-video 已落地到真实 *-viral 模板。
_THEME_RULES = [
    # (关键词, 题材标签, 目标模板, 说明)
    (["avatar", "头像", "face", "换脸", "写真", "portrait"], "avatar", "avatar-viral", "AI 头像/写真"),
    (["sticker", "表情", "meme", "emoji", "卡通"], "sticker", "sticker-viral", "表情包/贴纸"),
    (["pet", "宠物", "talk", "说话", "voice", "配音"], "pet-talk", "pet-talk-viral", "宠物说话/配音"),
    (["blessing", "祝福", "greeting", "新年", "节日"], "blessing-video", "blessing-video-viral", "祝福视频/贺卡"),
    (["funny", "搞笑", "video", "视频", "clip"], "funny-video", "funny-video-viral", "搞笑短视频"),
    # 抠图/去背景（image-to-image）：必须排在通用 photo/image 规则之前，
    # 否则 "background remover" 会被笼统归到 ai-image（文字出图），名实不符。
    (["background remover", "background removal", "remove background", "背景去除", "去背景", "抠图", "cutout", "cut out", "matting", "remove bg", "transparent background"],
     "bg-remove", "background-remover", "背景去除/抠图"),
    (["photo", "图片", "image", "art", "绘画", "draw"], "image-tool", "ai-image", "图像处理/生成"),
    (["writing", "写作", "translate", "翻译", "text", "summarize", "摘要"], "text-tool", "ai-tool", "文本/写作类"),
]
_DEFAULT = ("general-tool", "ai-tool", "通用 AI 工具")


def _text(app: dict) -> str:
    parts = [
        app.get("name", ""), app.get("name_cn", ""),
        app.get("category", ""), app.get("description", ""),
        app.get("description_cn", ""),
        " ".join(app.get("features", []) or []),
        " ".join(app.get("features_cn", []) or []),
        # feature 级输入：功能名 / 父 App / 拆分理由也参与题材判断
        app.get("feature_name", ""), app.get("feature_name_cn", ""),
        " ".join(app.get("reason", []) or []),
    ]
    return " ".join(parts).lower()


# 上游可直接给定模板（FeatureOpportunity.selected_template / classifier 已选）。
# 这些是 generator 真实支持的模板目录名，尊重上游时需在白名单内。
_KNOWN_TEMPLATES = {
    "ai-tool", "ai-chat", "ai-image",
    "avatar-viral", "sticker-viral", "pet-talk-viral",
    "funny-video-viral", "blessing-video-viral",
    "background-remover",
}
# 模板 -> 题材标签（尊重上游时回填展示用），与 _THEME_RULES 对齐。
_TEMPLATE_THEME_LABEL = {
    "ai-image": ("image-tool", "图像处理/生成"),
    "avatar-viral": ("avatar", "AI 头像/写真"),
    "sticker-viral": ("sticker", "表情包/贴纸"),
    "pet-talk-viral": ("pet-talk", "宠物说话/配音"),
    "blessing-video-viral": ("blessing-video", "祝福视频/贺卡"),
    "funny-video-viral": ("funny-video", "搞笑短视频"),
    "background-remover": ("bg-remove", "背景去除/抠图"),
    "ai-chat": ("chat-tool", "聊天/助手"),
    "ai-tool": ("general-tool", "通用 AI 工具"),
}


def classify(app: dict, viral: dict | None = None) -> dict:
    """归类题材并选择模板类型。返回 template-selection.json 内容。

    选择优先级（不允许拍脑袋）：
      1. 上游已给 selected_template 且在白名单 -> 直接尊重（FeatureOpportunity 核心）
      2. 否则按 feature_name/description/features 关键词命中数打分（命中最多者胜）
      3. 都不命中 -> 落 ai-tool（不失败）
    上游给了但模板不存在 -> 仍落 ai-tool，并在 rationale 标注（codegen 层会硬校验报错）。
    """
    upstream = (app.get("selected_template") or "").strip()
    viral_tier = (viral or {}).get("tier", "unknown")
    priority = "high" if viral_tier == "high" else ("medium" if viral_tier == "medium" else "normal")

    if upstream and upstream in _KNOWN_TEMPLATES:
        theme, theme_label = _TEMPLATE_THEME_LABEL.get(upstream, ("general-tool", "通用 AI 工具"))
        return {
            "app_name": app.get("name", ""),
            "app_name_cn": app.get("name_cn", ""),
            "theme": theme,
            "theme_label": theme_label,
            "selected_template": upstream,
            "matched_keywords": [],
            "viral_tier": viral_tier,
            "priority": priority,
            "selection_source": "upstream",
            "rationale": f"尊重上游指定模板 {upstream}（题材「{theme_label}」）；传播力 {viral_tier}，排期 {priority}。",
            "data_source": "demo_rule_based",
        }

    upstream_invalid = bool(upstream) and upstream not in _KNOWN_TEMPLATES

    text = _text(app)

    theme, template, theme_label = _DEFAULT
    matched_keywords: list[str] = []

    best_score = 0
    for keywords, t_theme, t_template, label in _THEME_RULES:
        hits = [kw for kw in keywords if kw in text]
        if len(hits) > best_score:
            best_score = len(hits)
            theme = t_theme
            template = t_template
            theme_label = label
            matched_keywords = hits

    rationale = f"题材归类为「{theme_label}」，选用模板 {template}；传播力 {viral_tier}，排期优先级 {priority}。"
    if upstream_invalid:
        rationale = f"上游指定模板 {upstream!r} 不在支持列表，已按关键词回退。" + rationale

    return {
        "app_name": app.get("name", ""),
        "app_name_cn": app.get("name_cn", ""),
        "theme": theme,
        "theme_label": theme_label,
        "selected_template": template,
        "matched_keywords": matched_keywords,
        "viral_tier": viral_tier,
        "priority": priority,
        "selection_source": "classifier",
        "upstream_invalid_template": upstream if upstream_invalid else None,
        "rationale": rationale,
        "data_source": "demo_rule_based",
    }


# template -> (ability, task)。ability 决定页面壳，task 决定后端意图。
# v1 白名单 task 只含已验证名副其实的两个；其余落 "pending"（不自动上线）。
_TEMPLATE_ABILITY_TASK = {
    "ai-image": ("text2img", "generate_image"),
    "background-remover": ("img2img", "background_remove"),
}


def template_to_ability_task(template: str) -> tuple[str, str]:
    """把 classifier 选出的 template 映射为合集渲染所需的 (ability, task)。

    不在 v1 白名单的 template -> ("text2img", "pending")：仍可渲染壳，
    但 task=pending 表示后端意图未经验证，registry 校验会拒绝其自动上线。
    """
    return _TEMPLATE_ABILITY_TASK.get(template, ("text2img", "pending"))
