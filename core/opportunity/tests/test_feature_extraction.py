"""大 App 功能拆解测试。"""

from __future__ import annotations

from core.opportunity.feature_extraction import extract_features, extract_all
from core.opportunity import feature_extraction_llm as fx


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


def test_background_remover_maps_to_background_remover_template():
    candidate = {
        "canonical_key": "app_store:com.x.sticker",
        "name": "Sticker Maker",
        "description": "background remover and cutout tool",
        "features": ["background remover"],
    }
    feats = extract_features(candidate)
    bg = [f for f in feats if "background" in f["feature_name"].lower()]
    assert bg, "background_remover feature should be extracted"
    assert bg[0]["selected_template"] == "background-remover"


def test_extract_all_rule_mode_default():
    """enrich=False(默认)走规则版，产物打 data_source=rule_fallback。"""
    feats = extract_all([_capcut()])
    assert feats
    assert all(f.get("data_source") == "rule_fallback" for f in feats)
    # 规则版产物也带 auto_publishable 字段(下游统一)
    assert all("auto_publishable" in f for f in feats)


def test_extract_all_enrich_falls_back_on_llm_failure(monkeypatch):
    """enrich=True 但 LLM 失败 → 整体回退规则版，不断流、不抛、不产脏数据。"""
    monkeypatch.setattr(fx, "extract_features_llm",
                        lambda app, top_n=5: (_ for _ in ()).throw(RuntimeError("down")))
    feats = extract_all([_capcut()], enrich=True)
    assert feats  # 不断流
    assert all(f.get("data_source") == "rule_fallback" for f in feats)


def test_extract_all_enrich_uses_llm_when_ok(monkeypatch):
    """enrich=True 且 LLM 正常 → 产物 data_source=llm。"""
    def _fake(app, top_n=5):
        return [{"feature_key": "app_store:123:bg", "parent_app_key": "app_store:123",
                 "parent_app_name": "CapCut", "feature_name": "BG", "feature_name_cn": "背景去除",
                 "ability_type": "bg-remove", "buildable": True, "auto_publishable": True,
                 "selected_template": "background-remover", "production_recommended": True,
                 "miniapp_fit_score": 86, "data_source": "llm",
                 "required_capabilities": ["image_generation"], "unsupported_reasons": []}]
    monkeypatch.setattr(fx, "extract_features_llm", _fake)
    feats = extract_all([_capcut()], enrich=True)
    assert all(f.get("data_source") == "llm" for f in feats)
