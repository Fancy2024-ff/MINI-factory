import json
from pathlib import Path

import pytest

from core.publisher.feature_registry import (
    build_feature_config,
    validate_feature,
    append_feature,
    ABILITY_WHITELIST,
    TASK_WHITELIST,
)


def test_build_from_app_and_selection():
    best_app = {"name_cn": "表情包", "description_cn": "一句话生成表情贴纸"}
    selection = {"selected_template": "ai-image", "theme": "image-tool"}
    feat = build_feature_config("app_store:com.x.sticker:sticker", best_app, selection)
    assert feat["id"] == "app-store-com-x-sticker-sticker"
    assert feat["ability"] == "text2img"
    assert feat["task"] == "generate_image"
    assert feat["title"] == "表情包"


def test_validate_rejects_unknown_task():
    feat = {"id": "x", "title": "t", "icon": "🎨", "ability": "img2img",
            "task": "restore", "subtitle": "s", "input": {"imageRequired": True},
            "params": {}, "ui": {"submitLabel": "go"}}
    ok, reason = validate_feature(feat)
    assert ok is False and "task" in reason


def test_validate_rejects_ability_input_mismatch():
    feat = {"id": "x", "title": "t", "icon": "🎨", "ability": "img2img",
            "task": "background_remove", "subtitle": "s",
            "input": {"imageRequired": False}, "params": {}, "ui": {"submitLabel": "go"}}
    ok, reason = validate_feature(feat)
    assert ok is False and "imageRequired" in reason


def test_append_skips_duplicate_id(tmp_path):
    reg = tmp_path / "features.generated.json"
    reg.write_text("[]", encoding="utf-8")
    feat = {"id": "dup", "title": "t", "icon": "🎨", "ability": "text2img",
            "task": "generate_image", "subtitle": "s",
            "input": {"textRequired": True}, "params": {"promptTemplate": "{input}"},
            "ui": {"submitLabel": "go"}}
    assert append_feature(reg, feat) is True
    assert append_feature(reg, feat) is False  # 同 id 跳过
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert len(data) == 1
