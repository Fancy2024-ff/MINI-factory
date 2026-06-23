"""大 App 功能拆解测试。"""

from __future__ import annotations

from core.opportunity.feature_extraction import extract_features


def _capcut():
    return {
        "canonical_key": "app_store:123",
        "name": "CapCut",
        "name_cn": "剪映",
        "description": (
            "All-in-one video editor with AI photo retouch, background remover, "
            "photo enhancer, AI avatar maker, and AI subtitles for long video. "
            "Professional timeline editing."
        ),
        "categories": ["Photo & Video"],
        "keywords": ["AI video", "video editor"],
        "appear_count": 4,
        "rating": 4.8,
    }


def test_capcut_yields_ai_photo_retouch():
    feats = extract_features(_capcut())
    names = {f["feature_name"] for f in feats}
    assert "AI photo retouch" in names
    retouch = next(f for f in feats if f["feature_name"] == "AI photo retouch")
    assert retouch["production_recommended"] is True
    assert retouch["selected_template"] == "ai-image"


def test_capcut_long_video_subtitles_marked_unsupported():
    feats = extract_features(_capcut())
    subs = [f for f in feats if "subtitle" in f["feature_name"].lower()]
    assert subs, "应识别出长视频字幕功能"
    assert subs[0]["production_recommended"] is False
    assert subs[0]["miniapp_fit_score"] <= 40
    assert subs[0]["unsupported_reasons"]


def test_video_editing_marked_low_fit():
    feats = extract_features(_capcut())
    editing = [f for f in feats if f["feature_name"] == "Long video editing"]
    assert editing and editing[0]["production_recommended"] is False


def test_photo_enhancer_maps_to_ai_image():
    cand = {"canonical_key": "k", "name": "Enhancer", "description": "photo enhancer, old photo 修复"}
    feats = extract_features(cand)
    enh = [f for f in feats if f["feature_name"] == "Photo enhancer"]
    assert enh and enh[0]["selected_template"] == "ai-image"


def test_avatar_feature_maps_to_avatar_template():
    cand = {"canonical_key": "k", "name": "AvatarApp", "description": "AI avatar and 头像 portrait maker"}
    feats = extract_features(cand)
    av = [f for f in feats if f["feature_name"] == "AI avatar"]
    assert av and av[0]["selected_template"] == "avatar-viral"


def test_one_big_app_yields_multiple_opportunities():
    feats = extract_features(_capcut())
    doable = [f for f in feats if f["production_recommended"]]
    # CapCut 文本含 retouch / background remover / enhancer / avatar，多于 1 个机会
    assert len(doable) >= 3


def test_unrelated_app_yields_nothing_doable():
    cand = {"canonical_key": "k", "name": "Bank", "description": "mobile banking and finance"}
    feats = extract_features(cand)
    assert all(not f["production_recommended"] for f in feats)
