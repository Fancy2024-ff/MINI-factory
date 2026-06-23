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


def update_status(
    queue: list[dict],
    queue_id: str,
    status: str,
    error: str | None = None,
) -> list[dict]:
    """更新指定 queue item 状态（produced/failed/in_progress）。"""
    for item in queue:
        if item.get("queue_id") == queue_id:
            item["status"] = status
            item["updated_at"] = _now_iso()
            if status == "failed":
                item["retry_count"] = int(item.get("retry_count", 0)) + 1
                if error:
                    item["last_error"] = error[:300]
            break
    return queue


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
