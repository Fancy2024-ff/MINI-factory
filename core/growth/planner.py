"""core.growth.planner — 增长策略，产出 growth-plan.md。

职责：基于候选 + viral score + 模板选择，生成可执行的增长计划正文。
按「传播力分层（tier）」给增长重心，再叠加「题材（theme）差异化打法」——
头像走社交展示、表情包走群聊流通、宠物走情感共鸣，冷启动/渠道/钩子各不同。
规则版 v1。产物 = growth-plan.md。
"""

from __future__ import annotations


# 题材差异化增长打法。key 对齐 classifier 的 theme / 模板题材。
# 每条给：增长抓手（angle）、冷启动场景（cold_start）、侧重渠道（channels）、
# 题材裂变钩子（loop）、题材关键指标（metric）。
_THEME_PLAYBOOK = {
    "avatar": {
        "angle": "头像是强社交展示物，换头像天然带动好友围观与追问「这哪做的」",
        "cold_start": "在头像/二次元/cos 社群投放多风格样张，引导「上传同款」",
        "channels": ["微信社群", "小红书风格种草", "QQ/微博头像话题", "校园群体"],
        "loop": "多风格解锁制造收集欲，单用户反复生成多套头像并替换主页头像",
        "metric": "头像导出率、风格解锁数/人、换头像后好友点开率",
    },
    "sticker": {
        "angle": "表情包是群聊高频流通物，单套表情可在多个群反复传播",
        "cold_start": "蹭热点梗做成套表情，在表情包/沙雕群首发引导转发",
        "channels": ["微信群聊", "QQ 表情", "微博热梗", "贴吧/豆瓣兴趣组"],
        "loop": "分享到群聊解锁更多表情，群聊每次斗图都是一次拉新触点",
        "metric": "整套导出率、单套被转发群数、群聊解锁转化率",
    },
    "pet-talk": {
        "angle": "宠物内容自带情感共鸣，朋友圈分享转化率高",
        "cold_start": "在宠物/萌宠社群投放「会说话的宠物」样片，引导用户配自家宠物台词",
        "channels": ["微信朋友圈", "抖音/快手萌宠", "小红书晒宠", "宠物社群"],
        "loop": "台词可定制带来反复创作，单只宠物产出多条；分享朋友圈解锁高清",
        "metric": "成片分享率、单宠物生成条数、朋友圈带来的新用户数",
    },
    "image-tool": {
        "angle": "修图前后对比是强视觉钩子，「同一张图差距」天然引发围观",
        "cold_start": "在摄影/修图/电商主图社群投放前后对比图，引导上传自己的图试一张",
        "channels": ["微信社群", "小红书修图教程", "抖音前后对比", "电商卖家群"],
        "loop": "每日免费额度 + 分享去水印/高清导出；邀请解锁更多修图风格",
        "metric": "出图率、前后对比分享率、去水印转化、邀请解锁数/人",
    },
    "funny-video": {
        "angle": "搞笑脚本/分镜是可复用拍摄模板，接龙挑战天然带动多人参与",
        "cold_start": "在沙雕/搞笑/短视频创作社群投放热门主题脚本，发起接龙挑战",
        "channels": ["抖音/快手挑战", "微信群接龙", "B 站二创", "微博热梗"],
        "loop": "分享发起挑战解锁更多分镜模板；热门脚本复用激发 UGC 二次创作",
        "metric": "挑战发起数、脚本复用率、单主题衍生视频数、接龙参与人数",
    },
    "blessing-video": {
        "angle": "节日祝福是强社交转发场景，带收件人姓名的个性化贺卡转发率高",
        "cold_start": "卡节日节点，在家庭群/同事群投放可定制姓名的祝福贺卡样例",
        "channels": ["微信家庭群/同事群", "朋友圈节日刷屏", "公众号节日推送"],
        "loop": "收件人个性化 + 群发裂变；转发解锁更多节日模板包",
        "metric": "节日期间生成量、贺卡转发率、群发触达人数、模板包解锁数",
    },
}
_DEFAULT_PLAYBOOK = {
    "angle": "靠工具价值与可晒结果驱动口碑传播",
    "cold_start": "在精准兴趣社群投放可晒样例，引导用户产出并分享结果",
    "channels": ["微信社群", "小红书", "公众号", "搜索流量"],
    "loop": "结果页一键分享带小程序码回流，邀请得额度",
    "metric": "分享率、邀请转化、次日留存",
}


def _playbook(selection: dict) -> dict:
    """按题材取差异化打法；theme 直接命中，否则按 selected_template 映射兜底。"""
    theme = (selection.get("theme") or "").strip()
    if theme in _THEME_PLAYBOOK:
        return _THEME_PLAYBOOK[theme]
    # selected_template -> playbook key 兜底映射（theme 缺失/不一致时）
    template = (selection.get("selected_template") or "")
    template_to_key = {
        "ai-image": "image-tool",
        "avatar-viral": "avatar",
        "sticker-viral": "sticker",
        "pet-talk-viral": "pet-talk",
        "funny-video-viral": "funny-video",
        "blessing-video-viral": "blessing-video",
    }
    key = template_to_key.get(template)
    if key and key in _THEME_PLAYBOOK:
        return _THEME_PLAYBOOK[key]
    return _DEFAULT_PLAYBOOK


def build_growth_plan(app: dict, viral: dict, selection: dict) -> str:
    """生成 growth-plan.md 正文（markdown）。"""
    name = app.get("name_cn") or app.get("name", "小程序")
    tier = viral.get("tier", "unknown")
    score = viral.get("viral_score", 0)
    theme_label = selection.get("theme_label", "通用工具")
    dims = viral.get("dimensions", {})
    play = _playbook(selection)

    # 按传播力分层给不同的增长重心
    if tier == "high":
        focus = "以裂变拉新为主引擎，分享即增长"
        channels = ["微信社群裂变", "朋友圈晒结果", "短视频平台话题挑战", "小程序互推"]
    elif tier == "medium":
        focus = "分享钩子 + 内容种草并重"
        channels = ["微信社群", "小红书种草", "朋友圈", "公众号导流"]
    else:
        focus = "工具价值留存为主，增长靠口碑与复用"
        channels = ["搜索流量", "公众号", "工具类聚合导流"]

    # 题材化渠道优先：题材专属渠道排在分层通用渠道之前，去重保序。
    merged_channels = play["channels"] + [c for c in channels if c not in play["channels"]]

    reward_hint = "高" if dims.get("reward_loop", 0) >= 70 else "中"

    lines = [
        f"# {name} 增长计划（growth-plan）",
        "",
        f"> 题材：{theme_label} ｜ Viral Score：{score}（{tier}）",
        "",
        "## 一、增长重心",
        f"- 分层重心（传播力 {tier}）：{focus}",
        f"- 题材抓手：{play['angle']}",
        f"- 裂变位适配度：{reward_hint}（reward_loop={dims.get('reward_loop', 0)}）",
        "",
        "## 二、冷启动（0 → 1000 用户）",
        f"1. 题材冷启动：{play['cold_start']}",
        "2. 首屏即出结果：降低门槛，让用户 10 秒内产出可分享内容",
        "3. 结果页内置「分享得额度/解锁」钩子（见 share-strategy.md）",
        "",
        "## 三、增长渠道（题材优先）",
    ]
    for c in merged_channels:
        lines.append(f"- {c}")
    lines += [
        "",
        "## 四、裂变回环设计",
        f"- 题材裂变钩子：{play['loop']}",
        "- 邀请 N 位好友 → 解锁高级模板/去水印/额外次数",
        "- 结果页一键生成分享卡片，带小程序码回流",
        "- 排行榜/挑战赛激发二次创作与传播",
        "",
        "## 五、留存与变现",
        f"- 变现模式参考：{app.get('monetization', 'freemium')}",
        "- 免费出基础结果，付费/邀请解锁高级能力",
        "- 推送节日/热点题材，唤醒沉默用户",
        "",
        "## 六、关键指标",
        f"- 题材专属指标：{play['metric']}",
        "- K 因子（每用户带来的新用户数）目标 > 1.0",
        "- 分享率（分享用户 / 出结果用户）目标 > 30%",
        "- 次日留存目标 > 25%",
        "",
        "> 本计划为规则版 v1，后续可由 LLM 按真实题材细化。",
        "",
    ]
    return "\n".join(lines)
