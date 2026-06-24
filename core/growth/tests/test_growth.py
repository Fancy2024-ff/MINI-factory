"""core.growth 测试：planner / share_strategy 产物含必要要素。"""

from core.growth.planner import build_growth_plan
from core.growth.share_strategy import build_share_strategy


_APP = {"name": "AI Avatar", "name_cn": "AI头像", "monetization": "freemium"}
_VIRAL = {"viral_score": 89.0, "tier": "high", "dimensions": {"reward_loop": 80, "low_friction": 90}}
_SEL = {"theme": "avatar", "theme_label": "AI 头像/写真", "selected_template": "ai-tool"}


def test_growth_plan_has_required_sections():
    md = build_growth_plan(_APP, _VIRAL, _SEL)
    for kw in ["增长重心", "渠道", "裂变", "指标"]:
        assert kw in md


def test_share_strategy_has_required_sections():
    md = build_share_strategy(_APP, _VIRAL, _SEL)
    for kw in ["分享钩子", "激励", "裂变", "水印"]:
        assert kw in md


def test_share_strategy_theme_specific_hooks():
    md = build_share_strategy(_APP, _VIRAL, _SEL)
    # avatar 题材应出现头像相关钩子
    assert "头像" in md


def test_growth_plan_theme_differentiated():
    """题材差异化：avatar / sticker / pet-talk 的增长计划应各有专属抓手与指标。"""
    avatar = build_growth_plan(_APP, _VIRAL, {"theme": "avatar", "theme_label": "AI 头像", "selected_template": "avatar-viral"})
    sticker = build_growth_plan(_APP, _VIRAL, {"theme": "sticker", "theme_label": "表情包", "selected_template": "sticker-viral"})
    pet = build_growth_plan(_APP, _VIRAL, {"theme": "pet-talk", "theme_label": "宠物说话", "selected_template": "pet-talk-viral"})

    # 各自题材抓手出现，且互不串台
    assert "社交展示物" in avatar or "围观" in avatar
    assert "群聊" in sticker and "斗图" in sticker
    assert "朋友圈" in pet and "宠物" in pet

    # 题材专属指标各不相同
    assert "换头像后好友点开率" in avatar
    assert "群数" in sticker
    assert "单宠物生成条数" in pet

    # 通用必备 section 仍在（不破坏原契约）
    for md in (avatar, sticker, pet):
        for kw in ["增长重心", "渠道", "裂变", "指标"]:
            assert kw in md


def test_growth_plan_unknown_theme_falls_back():
    """未知题材应回退到默认打法，不报错、section 齐全。"""
    md = build_growth_plan(_APP, _VIRAL, {"theme": "mystery", "theme_label": "未知", "selected_template": "ai-tool"})
    for kw in ["增长重心", "渠道", "裂变", "指标"]:
        assert kw in md


def test_growth_plan_covers_image_funny_blessing():
    """ai-image / funny-video / blessing-video 也要有差异化打法（不落默认）。"""
    image = build_growth_plan(_APP, _VIRAL, {"theme": "image-tool", "theme_label": "图像", "selected_template": "ai-image"})
    funny = build_growth_plan(_APP, _VIRAL, {"theme": "funny-video", "theme_label": "搞笑", "selected_template": "funny-video-viral"})
    blessing = build_growth_plan(_APP, _VIRAL, {"theme": "blessing-video", "theme_label": "祝福", "selected_template": "blessing-video-viral"})

    assert "前后对比" in image
    assert ("接龙" in funny or "挑战" in funny)
    assert ("节日" in blessing or "贺卡" in blessing)
    # 题材专属指标互不相同
    assert "去水印转化" in image
    assert "挑战发起数" in funny
    assert "贺卡转发率" in blessing


def test_growth_plan_playbook_via_selected_template_only():
    """theme 缺失但有 selected_template 时，也能命中差异化打法。"""
    md = build_growth_plan(_APP, _VIRAL, {"theme": "", "theme_label": "", "selected_template": "ai-image"})
    assert "前后对比" in md


# --- 传播闭环 growth_loop 接入（P0-2）---


def _sel(tpl, theme):
    return {"theme": theme, "theme_label": theme, "selected_template": tpl}


def test_share_strategy_has_growth_loop_section():
    """share-strategy.md 必须含结构化传播闭环口径（分享 CTA / 解锁 / 去水印 / 品牌 / 导出 / 能力）。"""
    md = build_share_strategy(_APP, _VIRAL, _sel("avatar-viral", "avatar"))
    assert "传播闭环" in md
    assert "分享 CTA" in md
    assert "解锁条件" in md
    assert "去水印" in md
    assert "品牌露出" in md
    assert "下载/导出" in md
    assert "当前能力" in md


def test_share_strategy_core_templates_differentiated():
    """三个核心模板的分享 CTA 文案必须不同（不是同一套通用壳）。"""
    avatar = build_share_strategy(_APP, _VIRAL, _sel("avatar-viral", "avatar"))
    sticker = build_share_strategy(_APP, _VIRAL, _sel("sticker-viral", "sticker"))
    pet = build_share_strategy(_APP, _VIRAL, _sel("pet-talk-viral", "pet-talk"))
    assert "分享头像" in avatar
    assert "分享到群聊" in sticker
    assert "分享宠物预览" in pet
    # 三者均标 real，无 fallback 边界声明
    for md in (avatar, sticker, pet):
        assert "real / 真实生成" in md
        assert "边界声明" not in md


def test_share_strategy_video_templates_mark_preview_boundary():
    """funny/blessing 必须明确 preview/fallback 边界，不伪装真实视频。"""
    for tpl, theme in (("funny-video-viral", "funny-video"), ("blessing-video-viral", "blessing-video")):
        md = build_share_strategy(_APP, _VIRAL, _sel(tpl, theme))
        assert "fallback / preview" in md
        assert "边界声明" in md
        assert "不是真实视频生成" in md


def test_growth_plan_has_growth_loop_summary():
    """growth-plan.md 含传播闭环摘要，但不做 Viral Score 维度解释（P0-3 边界）。"""
    md = build_growth_plan(_APP, _VIRAL, _sel("avatar-viral", "avatar"))
    assert "传播闭环摘要" in md
    assert "当前能力" in md
    # 仍保留原有 section
    for kw in ["增长重心", "渠道", "裂变", "指标"]:
        assert kw in md


def test_growth_plan_video_template_marks_preview():
    """funny/blessing 增长计划的传播闭环摘要必须标 fallback/preview 边界。"""
    md = build_growth_plan(_APP, _VIRAL, _sel("funny-video-viral", "funny-video"))
    assert "fallback / preview" in md
    assert "不是真实视频生成" in md
