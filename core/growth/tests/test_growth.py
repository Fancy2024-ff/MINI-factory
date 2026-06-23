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
