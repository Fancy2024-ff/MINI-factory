"""Pipeline queue 模式接入测试（不跑真实 build，只验队列消费与状态回写）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.pipeline.runner as runner
from core.opportunity import opportunity_queue as oq
from core.opportunity import processed_apps


@pytest.fixture
def queue_env(tmp_path, monkeypatch):
    """把 runner 的 OPPORTUNITY_DIR 指向 tmp，并写入一个 pending 队列。"""
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(runner, "OPPORTUNITY_DIR", opp)
    queue = [
        {
            "queue_id": "20260623-001",
            "feature_key": "app_store:1:ai_photo_retouch",
            "parent_app_key": "app_store:1",
            "parent_app_name": "CapCut",
            "feature_name_cn": "AI 修图",
            "final_score": 84.5,
            "selected_template": "ai-image",
            "status": "pending",
            "retry_count": 0,
            "score_breakdown": {"miniapp_fit": 86},
            "reason": ["功能轻量"],
        }
    ]
    (opp / "opportunity-queue.json").write_text(
        json.dumps(queue, ensure_ascii=False), encoding="utf-8"
    )
    runner._active_queue_item = None
    return opp


def test_queue_mode_loads_feature_app(queue_env):
    apps = runner.load_market_input(mode="queue")
    assert len(apps) == 1
    app = apps[0]
    assert app["selected_template"] == "ai-image"
    assert app["source_feature_key"] == "app_store:1:ai_photo_retouch"
    assert app["name_cn"] == "AI 修图"
    # 记录了当前消费项，供运行后回写
    assert runner._active_queue_item["queue_id"] == "20260623-001"


def test_queue_mode_empty_raises(tmp_path, monkeypatch):
    opp = tmp_path / "opportunity"
    opp.mkdir()
    (opp / "opportunity-queue.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(runner, "OPPORTUNITY_DIR", opp)
    with pytest.raises(ValueError):
        runner.load_market_input(mode="queue")


def test_update_queue_after_success(queue_env):
    runner.load_market_input(mode="queue")  # sets _active_queue_item
    runner._update_queue_after_run("job-xyz", success=True)

    queue = oq.load_queue(queue_env / "opportunity-queue.json")
    assert queue[0]["status"] == "produced"
    processed = processed_apps.load_processed(queue_env / "processed-apps.json")
    assert processed_apps.is_processed(processed, "app_store:1:ai_photo_retouch")


def test_update_queue_after_failure_increments_retry(queue_env):
    runner.load_market_input(mode="queue")
    runner._update_queue_after_run("job-xyz", success=False, error="build failed")

    queue = oq.load_queue(queue_env / "opportunity-queue.json")
    assert queue[0]["status"] == "failed"
    assert queue[0]["retry_count"] == 1
    processed = processed_apps.load_processed(queue_env / "processed-apps.json")
    assert processed_apps.retry_count(processed, "app_store:1:ai_photo_retouch") == 1
    assert not processed_apps.is_processed(processed, "app_store:1:ai_photo_retouch")


def test_classify_honors_preset_template():
    from core.opportunity.classifier import classify

    app = {"name": "AI 修图", "description_cn": "来自 CapCut 的能力", "selected_template": "ai-image"}
    sel = classify(app)
    assert sel["selected_template"] == "ai-image"
