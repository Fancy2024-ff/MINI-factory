"""AlertManager 测试：冷却去重、恢复防抖、双写容错、优雅降级。

用真实 TaskStore（tmp 文件库）做 alert_state 持久化，注入假 Telegram client + tmp 日志路径。
"""
from __future__ import annotations

import pytest

from core.runtime.task_store import TaskStore
from core.runtime.task_models import now_iso
from core.runtime.task_store import _add_seconds
from core.runtime.alerting import AlertManager


class FakeTG:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_message(self, chat_id, text):
        if self.fail:
            from core.platforms.telegram.api import TelegramAPIError
            raise TelegramAPIError("boom")
        self.sent.append((chat_id, text))


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.sqlite3")


def _mgr(store, tmp_path, tg=None, **kw):
    return AlertManager(store, telegram_client=tg, chat_id="c1",
                        log_path=tmp_path / "alerts.log",
                        cooldown_seconds=1800, recovery_confirmations=2, **kw)


def test_first_fire_sends(store, tmp_path):
    tg = FakeTG()
    m = _mgr(store, tmp_path, tg)
    assert m.fire("k", "msg") is True
    assert len(tg.sent) == 1


def test_fire_within_cooldown_suppressed(store, tmp_path):
    tg = FakeTG()
    m = _mgr(store, tmp_path, tg)
    now = now_iso()
    assert m.fire("k", "msg", now=now) is True
    # 冷却期内（+100s < 1800）再 fire：抑制
    assert m.fire("k", "msg", now=_add_seconds(now, 100)) is False
    assert len(tg.sent) == 1


def test_fire_after_cooldown_resends(store, tmp_path):
    tg = FakeTG()
    m = _mgr(store, tmp_path, tg)
    now = now_iso()
    m.fire("k", "msg", now=now)
    # 冷却过期（+2000s > 1800）：再发
    assert m.fire("k", "msg", now=_add_seconds(now, 2000)) is True
    assert len(tg.sent) == 2


def test_resolve_requires_consecutive_confirmations(store, tmp_path):
    tg = FakeTG()
    m = _mgr(store, tmp_path, tg)
    m.fire("k", "down")           # 进入告警态
    assert m.resolve("k") is False   # 第 1 次确认：不发
    assert m.resolve("k") is True    # 第 2 次确认：发"已恢复"
    assert any("恢复" in t for _, t in tg.sent)


def test_resolve_jitter_does_not_emit(store, tmp_path):
    tg = FakeTG()
    m = _mgr(store, tmp_path, tg)
    m.fire("k", "down")
    m.resolve("k")          # confirm=1
    m.fire("k", "down again")  # 抖动：重新告警，confirm 归零
    assert m.resolve("k") is False  # 又只有 1 次确认，不发恢复
    recoveries = [t for _, t in tg.sent if "恢复" in t]
    assert recoveries == []


def test_telegram_failure_still_logs(store, tmp_path):
    tg = FakeTG(fail=True)
    m = _mgr(store, tmp_path, tg)
    # TG 抛错不应让 fire 抛出
    assert m.fire("k", "msg") is True
    log = (tmp_path / "alerts.log").read_text()
    assert "msg" in log


def test_no_telegram_configured_degrades(store, tmp_path):
    m = AlertManager(store, telegram_client=None, chat_id=None,
                     log_path=tmp_path / "alerts.log")
    assert m.fire("k", "msg") is True   # 不报错
    assert "msg" in (tmp_path / "alerts.log").read_text()
