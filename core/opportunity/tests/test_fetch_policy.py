"""fetch_policy 与 scraper 单请求级限速/重试测试 — 全程 mock，不打真实网络。"""

from __future__ import annotations

import pytest

from core.opportunity import fetch_policy
from core.opportunity import crawl_config as cfg


def test_default_headers_carry_user_agent():
    h = fetch_policy.default_headers()
    assert h["User-Agent"] == cfg.CRAWL_PARAMS["user_agent"]
    assert "MiniAppFactory" in h["User-Agent"]


def test_with_retry_retries_then_raises(monkeypatch):
    monkeypatch.setitem(cfg.CRAWL_PARAMS, "retry_base_delay", 0)
    attempts = {"n": 0}

    def boom():
        attempts["n"] += 1
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        fetch_policy.with_retry(boom)
    assert attempts["n"] == cfg.CRAWL_PARAMS["max_retries"]


def test_with_retry_succeeds_after_failure(monkeypatch):
    monkeypatch.setitem(cfg.CRAWL_PARAMS, "retry_base_delay", 0)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    assert fetch_policy.with_retry(flaky) == "ok"
    assert attempts["n"] == 2


def test_appstore_multi_keyword_paces_between_requests(monkeypatch):
    """App Store search 多关键词：每次请求之间调用 pace（单请求级限速）。"""
    from core.opportunity.scrapers import appstore

    pace_calls = {"n": 0}
    monkeypatch.setattr(appstore.fetch_policy, "pace", lambda: pace_calls.__setitem__("n", pace_calls["n"] + 1))
    monkeypatch.setattr(appstore.fetch_policy, "with_retry", lambda fn, **kw: {"results": []})

    appstore._fetch_via_itunes(["kw1", "kw2", "kw3"], limit=30, country="us")
    # 3 个关键词 → 第 2、3 次请求前各 pace 一次 = 2
    assert pace_calls["n"] == 2


def test_appstore_uses_fetch_policy_for_requests(monkeypatch):
    """App Store 正式请求经 fetch_policy（带 UA），不裸用 httpx。"""
    from core.opportunity.scrapers import appstore

    used = {"get_json": 0}

    def fake_get_json(url, params=None):
        used["get_json"] += 1
        return {"results": []}

    monkeypatch.setattr(appstore.fetch_policy, "get_json", fake_get_json)
    monkeypatch.setattr(appstore.fetch_policy, "pace", lambda: None)
    appstore._fetch_via_itunes(["kw1"], limit=10, country="jp")
    assert used["get_json"] >= 1
