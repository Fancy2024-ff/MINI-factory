"""core.opportunity.fetch_policy — 统一抓取请求策略（合规低频，单请求级生效）。

把限速 / UA / timeout / jitter / retry / backoff 收口到一处，scraper 与 crawl_runner
共用，确保「防封」落到单请求级别，而不是只在外层 sleep。

不做代理池 / 账号绕限 / cookie 绕封；只做合规低频、重试、失败降级。
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx

from core.opportunity import crawl_config as cfg


def user_agent() -> str:
    return cfg.CRAWL_PARAMS["user_agent"]


def default_headers() -> dict[str, str]:
    """正式请求统一 headers（含 UA）。"""
    return {"User-Agent": user_agent(), "Accept": "application/json"}


def request_timeout() -> int:
    return cfg.CRAWL_PARAMS["request_timeout"]


def pace() -> None:
    """单请求级节奏：min_interval + 随机 jitter。多关键词循环每次请求之间也要调用。"""
    interval = cfg.CRAWL_PARAMS["min_interval_seconds"]
    jitter = random.uniform(0, cfg.CRAWL_PARAMS["jitter_seconds"])
    time.sleep(interval + jitter)


def get_json(url: str, params: dict | None = None) -> Any:
    """统一 httpx GET（带 UA + timeout），返回解析后的 JSON。异常向上抛由调用方降级。"""
    resp = httpx.get(url, params=params, headers=default_headers(), timeout=request_timeout())
    resp.raise_for_status()
    return resp.json()


def with_retry(fn: Callable[[], Any], *, on_error: Callable[[str], None] | None = None) -> Any:
    """指数退避重试包装。全部失败抛最后一个异常（调用方决定降级）。

    每次重试前退避 base * 2**attempt。不死循环（受 max_retries 限制）。
    """
    max_retries = cfg.CRAWL_PARAMS["max_retries"]
    base = cfg.CRAWL_PARAMS["retry_base_delay"]
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 抓取失败统一退避重试
            last_exc = e
            if on_error:
                on_error(f"{type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                time.sleep(base * (2 ** attempt))
    assert last_exc is not None
    raise last_exc
