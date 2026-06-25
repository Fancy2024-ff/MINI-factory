"""已处理 app 集合（app 级去重）测试。

processed_app_keys 返回「已进流水线且不可重做」的 app canonical_key 集合，
供 API 在返回候选列表时做差集过滤。failed/skipped/pending 不计入
（允许失败的 app 重新出现在候选列表，便于重试）。
"""

from __future__ import annotations

from core.opportunity.processed_apps import processed_app_keys


def test_produced_processed_record_is_included():
    processed = {
        "features": {
            "app_store:1:sticker": {"status": "produced", "parent_app_key": "app_store:1"},
        }
    }
    assert processed_app_keys(processed, []) == {"app_store:1"}


def test_queued_queue_item_is_included():
    queue = [{"queue_id": "d-001", "parent_app_key": "app_store:2", "status": "queued"}]
    assert processed_app_keys({"features": {}}, queue) == {"app_store:2"}


def test_produced_queue_item_is_included():
    queue = [{"queue_id": "d-001", "parent_app_key": "app_store:3", "status": "produced"}]
    assert processed_app_keys({"features": {}}, queue) == {"app_store:3"}


def test_failed_and_skipped_and_pending_are_excluded():
    """失败/跳过/待处理的 app 不隐藏——失败的要能重新出现以便重试。"""
    queue = [
        {"queue_id": "d-001", "parent_app_key": "app_store:failed", "status": "failed"},
        {"queue_id": "d-002", "parent_app_key": "app_store:skipped", "status": "skipped"},
        {"queue_id": "d-003", "parent_app_key": "app_store:pending", "status": "pending"},
    ]
    assert processed_app_keys({"features": {}}, queue) == set()


def test_non_produced_processed_record_excluded():
    """processed-apps.json 里 status!=produced（如 failed）不计入。"""
    processed = {
        "features": {
            "app_store:1:sticker": {"status": "failed", "parent_app_key": "app_store:1"},
        }
    }
    assert processed_app_keys(processed, []) == set()


def test_union_of_both_sources():
    processed = {
        "features": {
            "app_store:a:meme": {"status": "produced", "parent_app_key": "app_store:a"},
        }
    }
    queue = [{"queue_id": "d-001", "parent_app_key": "app_store:b", "status": "queued"}]
    assert processed_app_keys(processed, queue) == {"app_store:a", "app_store:b"}


def test_empty_inputs_return_empty_set():
    assert processed_app_keys({"features": {}}, []) == set()
    assert processed_app_keys({}, []) == set()


def test_missing_parent_app_key_is_skipped_safely():
    """字段缺失或为空时不应崩溃，也不产出空字符串 key。"""
    processed = {"features": {"x:y": {"status": "produced"}}}  # 无 parent_app_key
    queue = [
        {"queue_id": "d-001", "status": "queued"},          # 无 parent_app_key
        {"queue_id": "d-002", "parent_app_key": "", "status": "produced"},  # 空字符串
    ]
    assert processed_app_keys(processed, queue) == set()
