"""core.publisher.ad_config — 每个功能页（TG 合集站路由）的广告闸门配置。

控制下载前是否弹激励广告（上架/下架）以及倒计时秒数。按 route 维度存储，
含 `_default` 兜底。供：
  - dashboard 提交中心读写（管理）
  - TG 站运行时读取（决定是否/多久弹广告）

存储惯例同项目其余：data/ 下 JSON，UTF-8，indent=2。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 硬编码兜底：配置文件/默认项都缺失时用它，保证永远有可用值。
HARD_DEFAULT = {"ad_enabled": True, "ad_seconds": 30}
MIN_SECONDS = 0
MAX_SECONDS = 120


def load_ad_config(path: Path) -> dict:
    """读 ad-config.json；不存在/损坏返回只含 _default 的结构。"""
    path = Path(path)
    if not path.exists():
        return {"_default": dict(HARD_DEFAULT)}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"_default": dict(HARD_DEFAULT)}
    if not isinstance(data, dict):
        return {"_default": dict(HARD_DEFAULT)}
    data.setdefault("_default", dict(HARD_DEFAULT))
    return data


def resolve_ad(config: dict, route: str) -> dict:
    """解析某 route 的广告配置：route 记录 → _default → 硬编码兜底。

    返回规范化后的 {ad_enabled: bool, ad_seconds: int}。
    """
    config = config if isinstance(config, dict) else {}
    rec = config.get(route)
    default = config.get("_default") or {}
    merged = {**HARD_DEFAULT, **_clean(default), **_clean(rec)}
    return {
        "ad_enabled": bool(merged["ad_enabled"]),
        "ad_seconds": _clamp_seconds(merged["ad_seconds"]),
    }


def set_ad(config: dict, route: str, *, enabled: Any = None, seconds: Any = None) -> dict:
    """更新单个 route 的广告配置（只改传入的字段）。返回更新后的整份 config。"""
    if not isinstance(config, dict):
        config = {}
    rec = dict(config.get(route) or {})
    if enabled is not None:
        rec["ad_enabled"] = bool(enabled)
    if seconds is not None:
        rec["ad_seconds"] = _clamp_seconds(seconds)
    config[route] = rec
    return config


def save_ad_config(path: Path, config: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(rec: Any) -> dict:
    """只保留我们认识的字段，忽略脏数据。"""
    if not isinstance(rec, dict):
        return {}
    out: dict = {}
    if "ad_enabled" in rec:
        out["ad_enabled"] = rec["ad_enabled"]
    if "ad_seconds" in rec:
        out["ad_seconds"] = rec["ad_seconds"]
    return out


def _clamp_seconds(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return HARD_DEFAULT["ad_seconds"]
    return max(MIN_SECONDS, min(MAX_SECONDS, n))
