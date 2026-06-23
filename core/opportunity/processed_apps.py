"""core.opportunity.processed_apps — 已生产/已跳过记录（feature 级防重复）。

记录已生产或失败的 feature_key，避免同一功能重复进入生产队列。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_processed(path: Path) -> dict:
    """读取 processed-apps.json；不存在返回空结构。"""
    if not path.exists():
        return {"features": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"features": {}}
    if not isinstance(data, dict) or "features" not in data:
        return {"features": {}}
    return data


def save_processed(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_processed(data: dict, feature_key: str) -> bool:
    """feature 是否已成功生产。"""
    rec = data.get("features", {}).get(feature_key)
    return bool(rec) and rec.get("status") == "produced"


def retry_count(data: dict, feature_key: str) -> int:
    rec = data.get("features", {}).get(feature_key)
    return int(rec.get("retry_count", 0)) if rec else 0


def mark_produced(data: dict, feature_key: str, parent_app_key: str, job_id: str) -> dict:
    data.setdefault("features", {})[feature_key] = {
        "status": "produced",
        "parent_app_key": parent_app_key,
        "job_id": job_id,
        "produced_at": _now_iso(),
    }
    return data


def mark_failed(data: dict, feature_key: str, parent_app_key: str, error: str) -> dict:
    rec = data.setdefault("features", {}).get(feature_key) or {
        "parent_app_key": parent_app_key,
        "retry_count": 0,
    }
    rec["status"] = "failed"
    rec["parent_app_key"] = parent_app_key
    rec["retry_count"] = int(rec.get("retry_count", 0)) + 1
    rec["last_error"] = (error or "")[:300]
    rec["failed_at"] = _now_iso()
    data["features"][feature_key] = rec
    return data
