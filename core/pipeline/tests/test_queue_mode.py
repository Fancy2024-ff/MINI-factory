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


def _seed_multi(opp, monkeypatch):
    """写一个多 item 队列（不同顺序/状态），返回路径。"""
    queue = [
        {"queue_id": "Q-1", "feature_key": "app_store:1:a", "parent_app_key": "app_store:1",
         "parent_app_name": "AppOne", "feature_name_cn": "功能一",
         "selected_template": "ai-image", "status": "pending"},
        {"queue_id": "Q-2", "feature_key": "app_store:2:b", "parent_app_key": "app_store:2",
         "parent_app_name": "AppTwo", "feature_name_cn": "功能二",
         "selected_template": "avatar-viral", "status": "pending"},
        {"queue_id": "Q-3", "feature_key": "app_store:3:c", "parent_app_key": "app_store:3",
         "parent_app_name": "AppThree", "feature_name_cn": "功能三",
         "selected_template": "ai-image", "status": "failed", "retry_count": 1},
    ]
    (opp / "opportunity-queue.json").write_text(
        json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(runner, "OPPORTUNITY_DIR", opp)
    runner._active_queue_item = None


def test_targeted_queue_id_consumes_only_that_item(tmp_path, monkeypatch):
    """定向 queue mode：指定 queue_id 只消费目标 item，不消费队首。"""
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True)
    _seed_multi(opp, monkeypatch)
    apps = runner.load_market_input(mode="queue", queue_id="Q-2")
    assert len(apps) == 1
    assert apps[0]["source_queue_id"] == "Q-2"
    assert apps[0]["selected_template"] == "avatar-viral"
    assert runner._active_queue_item["queue_id"] == "Q-2"


def test_targeted_queue_id_can_consume_failed(tmp_path, monkeypatch):
    """定向消费允许 failed item（重新发起生成）。"""
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True)
    _seed_multi(opp, monkeypatch)
    apps = runner.load_market_input(mode="queue", queue_id="Q-3")
    assert apps[0]["source_queue_id"] == "Q-3"


def test_targeted_unknown_queue_id_raises(tmp_path, monkeypatch):
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True)
    _seed_multi(opp, monkeypatch)
    with pytest.raises(ValueError):
        runner.load_market_input(mode="queue", queue_id="NOPE")


def test_plain_queue_mode_still_consumes_first_pending(tmp_path, monkeypatch):
    """未指定 queue_id 时仍消费下一个 pending（兼容旧行为）。"""
    opp = tmp_path / "opportunity"
    opp.mkdir(parents=True)
    _seed_multi(opp, monkeypatch)
    apps = runner.load_market_input(mode="queue")
    assert apps[0]["source_queue_id"] == "Q-1"  # 第一个 pending


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
