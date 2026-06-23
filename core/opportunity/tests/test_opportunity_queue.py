"""生产队列测试。"""

from __future__ import annotations

from core.opportunity.opportunity_queue import (
    build_queue,
    pop_next_pending,
    update_status,
    queue_item_to_app_input,
)


def _ranked():
    return [
        {
            "feature_key": "app_store:1:ai_photo_retouch",
            "parent_app_key": "app_store:1",
            "parent_app_name": "CapCut",
            "feature_name_cn": "AI 修图",
            "final_score": 84.5,
            "selected_template": "ai-image",
            "score_breakdown": {"miniapp_fit": 86, "viral": 78},
            "reason": ["功能轻量"],
        },
        {
            "feature_key": "app_store:1:avatar",
            "parent_app_key": "app_store:1",
            "parent_app_name": "CapCut",
            "feature_name_cn": "AI 头像",
            "final_score": 80.0,
            "selected_template": "avatar-viral",
            "score_breakdown": {"miniapp_fit": 88},
            "reason": ["头像可分享"],
        },
    ]


def test_build_queue_has_breakdown_and_reason():
    q = build_queue(_ranked(), processed={"features": {}}, date_str="20260623")
    assert len(q) == 2
    assert q[0]["queue_id"] == "20260623-001"
    assert q[0]["status"] == "pending"
    assert q[0]["score_breakdown"] and q[0]["reason"]


def test_processed_feature_not_in_pending():
    processed = {"features": {"app_store:1:ai_photo_retouch": {"status": "produced"}}}
    q = build_queue(_ranked(), processed=processed, date_str="20260623")
    keys = {item["feature_key"] for item in q}
    assert "app_store:1:ai_photo_retouch" not in keys
    assert "app_store:1:avatar" in keys


def test_failed_feature_over_retry_limit_skipped():
    processed = {"features": {"app_store:1:avatar": {"status": "failed", "retry_count": 3}}}
    q = build_queue(_ranked(), processed=processed, max_retry_count=2, date_str="20260623")
    keys = {item["feature_key"] for item in q}
    assert "app_store:1:avatar" not in keys  # 超重试上限被跳过


def test_failed_feature_within_retry_limit_kept():
    processed = {"features": {"app_store:1:avatar": {"status": "failed", "retry_count": 1}}}
    q = build_queue(_ranked(), processed=processed, max_retry_count=2, date_str="20260623")
    keys = {item["feature_key"] for item in q}
    assert "app_store:1:avatar" in keys


def test_one_app_multiple_features_in_queue():
    q = build_queue(_ranked(), processed={"features": {}}, date_str="20260623")
    parents = [item["parent_app_key"] for item in q]
    assert parents.count("app_store:1") == 2  # 同一 App 多 feature 入队


def test_pop_and_update_status():
    q = build_queue(_ranked(), processed={"features": {}}, date_str="20260623")
    nxt = pop_next_pending(q)
    assert nxt["queue_id"] == "20260623-001"
    update_status(q, nxt["queue_id"], "produced")
    assert q[0]["status"] == "produced"
    # 下一个 pending 变成第二项
    assert pop_next_pending(q)["queue_id"] == "20260623-002"


def test_queue_item_to_app_input_carries_template():
    q = build_queue(_ranked(), processed={"features": {}}, date_str="20260623")
    app = queue_item_to_app_input(q[0])
    assert app["selected_template"] == "ai-image"
    assert app["source_feature_key"] == "app_store:1:ai_photo_retouch"
    assert app["name_cn"] == "AI 修图"


def test_update_status_failed_increments_retry():
    q = build_queue(_ranked(), processed={"features": {}}, date_str="20260623")
    update_status(q, "20260623-001", "failed", error="boom")
    assert q[0]["status"] == "failed"
    assert q[0]["retry_count"] == 1
    assert "boom" in q[0]["last_error"]
