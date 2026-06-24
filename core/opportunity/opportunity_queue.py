"""core.opportunity.opportunity_queue — 生产队列构建与消费。

把排序后的 FeatureOpportunity 转成 opportunity-queue.json（feature 级生产队列）。
- 已生产 feature_key 不进入 pending。
- failed 且 retry_count 超上限的不再入队。
- 提供 pop_next_pending（pipeline queue 模式消费）与状态更新。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.opportunity import processed_apps


# queue item 状态（最小集合）。pending=待消费；queued=已为其创建 task（task 系统持有）；
# produced=已生成；failed=生成失败；skipped=人工跳过。runner/worker 据此回写，
# task 系统是正式执行者（见 docs/operation/RUNBOOK.md）。
STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_PRODUCED = "produced"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# 定向消费可接受的状态：尚未生成成功、未被跳过的，都可被 --queue-id 定向消费。
_CONSUMABLE_STATUSES = (STATUS_PENDING, STATUS_QUEUED, STATUS_FAILED)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_queue(
    ranked_features: list[dict],
    processed: dict | None = None,
    max_retry_count: int = 2,
    skip_processed: bool = True,
    date_str: str | None = None,
) -> list[dict]:
    """把排序后的 feature 列表转成 queue items。

    processed: load_processed() 结果，用于跳过已生产/超重试的 feature。
    """
    processed = processed or {"features": {}}
    date_str = date_str or datetime.now().strftime("%Y%m%d")
    queue: list[dict] = []
    seq = 0
    for feat in ranked_features:
        fkey = feat.get("feature_key", "")
        if skip_processed and processed_apps.is_processed(processed, fkey):
            continue
        rc = processed_apps.retry_count(processed, fkey)
        if rc > max_retry_count:
            continue
        seq += 1
        queue.append({
            "queue_id": f"{date_str}-{seq:03d}",
            "feature_key": fkey,
            "parent_app_key": feat.get("parent_app_key", ""),
            "parent_app_name": feat.get("parent_app_name", ""),
            "feature_name_cn": feat.get("feature_name_cn", ""),
            "final_score": feat.get("final_score", 0),
            "selected_template": feat.get("selected_template", ""),
            "status": "pending",
            "retry_count": rc,
            "score_breakdown": feat.get("score_breakdown", {}),
            "reason": feat.get("reason", []),
            "required_capabilities": feat.get("required_capabilities", []),
        })
    return queue


def load_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_queue(path: Path, queue: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def pop_next_pending(queue: list[dict]) -> dict | None:
    """返回第一个 pending item（不修改 queue）。无则 None。"""
    for item in queue:
        if item.get("status") == "pending":
            return item
    return None


def find_consumable(queue: list[dict], queue_id: str) -> dict | None:
    """定向消费：返回指定 queue_id 且处于可消费状态的 item（不修改 queue）。

    可消费 = pending / queued / failed（即尚未成功生成、未被跳过）。用于 runner 的
    定向 queue mode（--queue-id）；命中即只消费该 item，绝不串到别的 item。
    """
    item = find_item(queue, queue_id)
    if item is None:
        return None
    if item.get("status") in _CONSUMABLE_STATUSES:
        return item
    return None


def mark_queued(queue: list[dict], queue_id: str, task_id: str = "", job_id: str = "") -> dict | None:
    """把 item 标为 queued 并记录持有它的 task_id / job_id（task↔queue item↔job 映射）。

    generate_now 创建 task 后调用，使 queue item 能追踪到正在为它执行的 task / job。
    """
    item = find_item(queue, queue_id)
    if item is None:
        return None
    item["status"] = STATUS_QUEUED
    if task_id:
        item["task_id"] = task_id
    if job_id:
        item["job_id"] = job_id
    item["updated_at"] = _now_iso()
    return item


def update_status(
    queue: list[dict],
    queue_id: str,
    status: str,
    error: str | None = None,
    job_id: str | None = None,
) -> list[dict]:
    """更新指定 queue item 状态（produced/failed/queued 等）。

    只更新匹配 queue_id 的那一个 item（绝不误改其它 item）。可附带 job_id 记录是哪个
    job 产出/失败的，便于 queue item↔job 追踪。
    """
    for item in queue:
        if item.get("queue_id") == queue_id:
            item["status"] = status
            item["updated_at"] = _now_iso()
            if job_id:
                item["job_id"] = job_id
            if status == "failed":
                item["retry_count"] = int(item.get("retry_count", 0)) + 1
                if error:
                    item["last_error"] = error[:300]
            break
    return queue


def find_item(queue: list[dict], queue_id: str) -> dict | None:
    for item in queue:
        if item.get("queue_id") == queue_id:
            return item
    return None


def prioritize(queue: list[dict], queue_id: str) -> dict | None:
    """把指定 item 提到队列最前（pending 优先消费）。返回被提权的 item。"""
    item = find_item(queue, queue_id)
    if item is None:
        return None
    queue.remove(item)
    queue.insert(0, item)
    item["priority_boosted"] = True
    item["updated_at"] = _now_iso()
    return item


def skip(queue: list[dict], queue_id: str) -> dict | None:
    """跳过指定 item（标记 skipped，不再进入消费）。"""
    item = find_item(queue, queue_id)
    if item is None:
        return None
    item["status"] = "skipped"
    item["updated_at"] = _now_iso()
    return item


def retry(queue: list[dict], queue_id: str) -> dict | None:
    """把 failed/skipped item 重置为 pending，可被再次消费。"""
    item = find_item(queue, queue_id)
    if item is None:
        return None
    item["status"] = "pending"
    item["updated_at"] = _now_iso()
    return item


def queue_item_to_app_input(item: dict) -> dict:
    """把 queue item 转成 pipeline 需要的 app 输入结构。

    pipeline 的 _normalize_app 会补全缺省字段；这里给出 feature 级的最小语义输入，
    并带上 selected_template 让生成使用指定模板。
    """
    name_cn = item.get("feature_name_cn", "") or item.get("parent_app_name", "")
    parent = item.get("parent_app_name", "")
    return {
        "name": item.get("feature_name_cn", "") or item.get("parent_app_name", "Feature App"),
        "name_cn": name_cn,
        "description": f"来自 {parent} 的轻量能力：{name_cn}",
        "description_cn": f"来自 {parent} 的轻量能力：{name_cn}",
        "features": [name_cn],
        "features_cn": [name_cn],
        "selected_template": item.get("selected_template", ""),
        "source_feature_key": item.get("feature_key", ""),
        "source_queue_id": item.get("queue_id", ""),
    }
