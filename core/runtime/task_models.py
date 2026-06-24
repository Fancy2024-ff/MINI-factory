"""core.runtime.task_models — 任务系统的状态/类型常量与序列化辅助。

属于运行时基础设施（runtime），不含队列存储逻辑（见 task_store.py）也不含
执行逻辑（见 core.pipeline.task_worker）。这里只定义：
- TaskStatus：合法状态集合 + 终态判断。
- TaskKind：支持的任务种类（与 payload 形态对应）。
- 合法状态流转表（STATUS_TRANSITIONS），供 store 校验与文档参考。
- payload / result / error 的 JSON 序列化辅助（防止脏数据进库 / 泄露密钥）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


class TaskStatus:
    """任务状态常量（用字符串常量而非 Enum，便于直接入库与 JSON 传输）。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ALL = (PENDING, RUNNING, SUCCEEDED, FAILED, CANCELLED)
    # 终态：不再被 worker claim，也不能再流转（除非 retry 显式重置）。
    TERMINAL = (SUCCEEDED, FAILED, CANCELLED)


class TaskKind:
    """任务种类常量。每种 kind 对应 task_worker 中的一个执行分支与一种 payload 形态。"""

    PIPELINE_RUN = "pipeline.run"        # 消费机会队列生成一个小程序（queue 模式）
    PIPELINE_AUTO = "pipeline.auto"      # 抓取 → 队列 → 生成 一键串联
    OPPORTUNITY_CRAWL = "opportunity.crawl"  # 只抓取生成 opportunity-queue

    ALL = (PIPELINE_RUN, PIPELINE_AUTO, OPPORTUNITY_CRAWL)


# 合法状态流转（from -> {to}）。store 在状态变更时据此校验，避免非法跳转。
# - pending  -> running                （worker claim）
# - running  -> succeeded              （complete）
# - running  -> failed                 （fail，且不可重试或已达上限）
# - running  -> pending                （fail，可重试，回队等待 backoff）
# - pending/running/failed -> cancelled（cancel）
# - failed   -> pending                （retry，手动重置）
# - running(stale) -> pending          （requeue_stale，锁过期回收）
STATUS_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.PENDING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.CANCELLED: set(),
}


def can_transition(from_status: str, to_status: str) -> bool:
    """判断 from_status -> to_status 是否为合法流转。"""
    return to_status in STATUS_TRANSITIONS.get(from_status, set())


def now_iso() -> str:
    """统一的 UTC ISO 时间戳（带时区），供入库/比较使用。"""
    return datetime.now(timezone.utc).isoformat()


def dumps(data: object) -> str:
    """把 payload/result 序列化为可入库的 JSON 字符串（中文不转义）。

    None 归一化为空对象字符串，保证列非空约束（payload_json NOT NULL DEFAULT '{}'）。
    """
    if data is None:
        return "{}"
    return json.dumps(data, ensure_ascii=False, default=str)


def loads(raw: str | None) -> object:
    """把入库 JSON 字符串还原为对象；空/损坏时返回 {}（不抛，避免读流程被脏数据打断）。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


# 错误信息脱敏：避免把可能的密钥/敏感配置写进 error_message 入库或回前端。
_SENSITIVE_HINTS = (
    "api_key", "apikey", "api-key", "secret", "token", "password", "passwd",
    "private_key", "authorization", "bearer",
)
_MAX_ERROR_LEN = 1000


def sanitize_error(message: str | None) -> str:
    """裁剪 + 脱敏错误信息。

    策略保守：长度截断到 _MAX_ERROR_LEN；若某行疑似包含敏感键名，则整行替换为占位，
    宁可少信息也不泄露密钥。不解析具体 value，按行启发式处理即可满足 MVP 要求。
    """
    if not message:
        return ""
    text = str(message)
    safe_lines = []
    for line in text.splitlines():
        low = line.lower()
        if any(hint in low for hint in _SENSITIVE_HINTS):
            safe_lines.append("[redacted: line may contain a secret]")
        else:
            safe_lines.append(line)
    cleaned = "\n".join(safe_lines)
    return cleaned[:_MAX_ERROR_LEN]
