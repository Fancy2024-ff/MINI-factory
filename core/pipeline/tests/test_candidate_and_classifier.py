"""候选选择 + 题材归类回归。

证明：
  1. Viral Score 真实改变候选选择（select_best_candidate），不是事后标签；
  2. classifier「命中数最多者胜」修复误判：funny 不被 sticker 抢，
     blessing 不被 generic video 抢，pet-talk 混合词不误落 funny-video。
"""

from core.pipeline.runner import select_best_candidate
from core.opportunity.classifier import classify
from core.opportunity.viral_score import compute_viral_score


def _app(name, name_cn, category, desc_cn, features_cn, monetization="freemium"):
    return {
        "name": name, "name_cn": name_cn, "category": category,
        "description": desc_cn, "description_cn": desc_cn,
        "features": features_cn, "features_cn": features_cn,
        "downloads": 1_000_000, "rating": 4.6, "monetization": monetization,
    }


# ----- [7] 候选选择受 viral_score 影响 -----

def test_viral_score_changes_selected_candidate():
    """两个需求分相近的候选，传播力高者应被选中。"""
    # 低传播：纯工具类（写作/发票），高传播：头像/视频类
    plain_tool = _app("Invoice Tool", "发票工具", "Productivity",
                       "发票管理与报销工具", ["发票管理", "报销"], "subscription")
    viral_app = _app("AI Avatar", "AI 头像写真", "Photo & Video",
                     "AI 一键生成头像写真，可分享解锁高清", ["AI 写真", "换脸", "高清导出"])

    best_app, best_analysis, best_viral, scored = select_best_candidate([plain_tool, viral_app])

    # 选中的是高传播候选
    assert best_app["name"] == "AI Avatar", scored
    # 高传播候选的 viral_score 明显高于纯工具
    v_plain = compute_viral_score(plain_tool)["viral_score"]
    v_viral = compute_viral_score(viral_app)["viral_score"]
    assert v_viral > v_plain
    # 决策分确实把 viral 计入（40% 权重）
    assert best_analysis["candidate_decision_score"] == round(
        best_analysis["demand_score"] * 0.60 + best_viral["viral_score"] * 0.40, 1
    )


def test_selection_flips_when_viral_dominates():
    """构造：A 需求略高但传播极低，B 需求略低但传播极高 → 选 B。"""
    # A：高下载工具（demand 高），低传播品类
    a = _app("Tax Helper", "报税助手", "Finance",
             "报税与财务计算工具", ["报税", "财务计算"], "subscription")
    a["downloads"] = 9_000_000
    # B：娱乐视频（传播极高），下载略低
    b = _app("Funny Video", "搞笑视频神器", "Entertainment",
             "一键生成爆笑搞笑短视频，带特效字幕，分享到短视频平台", ["搞笑视频", "特效", "字幕"])
    b["downloads"] = 5_000_000

    best_app, _, _, scored = select_best_candidate([a, b])
    assert best_app["name"] == "Funny Video", scored


# ----- [8] classifier 误判修复（命中数最多者胜）-----

def _classify_template(app):
    return classify(app, compute_viral_score(app))["selected_template"]


def test_funny_not_stolen_by_sticker_meme():
    # 含 meme（sticker 关键词）但主题是搞笑视频 → funny-video-viral
    app = _app("Funny Clip Maker", "搞笑视频神器", "Entertainment",
               "一键把素材做成爆笑搞笑短视频，自带 meme 沙雕特效、字幕和视频接龙",
               ["搞笑视频", "meme 特效", "视频接龙", "字幕"])
    assert _classify_template(app) == "funny-video-viral"


def test_blessing_not_stolen_by_generic_video():
    # 含 video（funny 关键词）但主题是祝福贺卡 → blessing-video-viral
    app = _app("Blessing Greeting", "祝福视频贺卡", "Lifestyle",
               "节日生日一键生成祝福视频贺卡，新年祝福转发送礼",
               ["祝福视频", "贺卡", "节日模板", "新年"])
    assert _classify_template(app) == "blessing-video-viral"


def test_pet_talk_mixed_words_not_funny():
    # 同时含 talk/voice/video 等混合词，但主题是宠物说话 → pet-talk-viral
    app = _app("Pet Talk", "宠物说话配音", "Entertainment",
               "上传宠物视频，AI 配音让宠物说话，一键配音分享",
               ["宠物说话", "配音", "voice", "视频"])
    assert _classify_template(app) == "pet-talk-viral"


def test_avatar_maps_to_avatar_viral():
    app = _app("AI Avatar Studio", "AI 头像写真馆", "Photo & Video",
               "上传自拍 AI 生成多风格头像写真，支持换脸",
               ["AI 写真", "换脸", "portrait"])
    assert _classify_template(app) == "avatar-viral"


# ----- 尊重上游 selected_template（FeatureOpportunity 核心） -----

def test_classifier_respects_upstream_selected_template():
    """上游给了有效模板 → 直接尊重，不按关键词重判。"""
    # 文本看起来像头像，但上游明确指定 ai-image → 必须用 ai-image
    app = _app("AI Avatar-ish", "看起来像头像", "Photo & Video",
               "头像 写真 portrait avatar", ["头像", "portrait"])
    app["selected_template"] = "ai-image"
    sel = classify(app, compute_viral_score(app))
    assert sel["selected_template"] == "ai-image"
    assert sel["selection_source"] == "upstream"


def test_classifier_invalid_upstream_falls_back_not_crash():
    """上游给了不存在的模板 → 回退关键词，不失败，并标注。"""
    app = _app("Sticker Maker", "表情包制作", "Entertainment",
               "一键生成表情包 sticker meme", ["表情包", "sticker"])
    app["selected_template"] = "nonexistent-template"
    sel = classify(app, compute_viral_score(app))
    assert sel["selected_template"] == "sticker-viral"  # 回退到关键词命中
    assert sel["selection_source"] == "classifier"
    assert sel["upstream_invalid_template"] == "nonexistent-template"


def test_classifier_no_match_falls_to_ai_tool():
    """无关键词命中、无上游 → 落 ai-tool，不失败。"""
    app = _app("Mystery", "神秘工具", "Utilities", "一个工具", ["功能"])
    sel = classify(app, compute_viral_score(app))
    assert sel["selected_template"] == "ai-tool"

