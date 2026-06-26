"""core.runtime.alerting — 告警引擎（去重/冷却/恢复防抖 + Telegram/本地日志双写）。

纯逻辑：状态存 TaskStore.alert_state（持久化，重启不丢）。不主动巡检——由 worker 维护
循环与 API 看门狗调 fire/resolve。Telegram best-effort（失败只记日志），本地日志必落。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.runtime import task_models as tm


class AlertManager:
    def __init__(self, store, *, telegram_client=None, chat_id=None, log_path=None,
                 cooldown_seconds: int = 1800, recovery_confirmations: int = 2):
        self.store = store
        self.tg = telegram_client
        self.chat_id = chat_id
        self.log_path = Path(log_path) if log_path else None
        self.cooldown_seconds = cooldown_seconds
        self.recovery_confirmations = recovery_confirmations

    def fire(self, alert_key: str, message: str, *, now: str | None = None) -> bool:
        """触发告警。冷却期内同 key 抑制；首次或冷却过期才发。返回是否真的发了。"""
        now = now or tm.now_iso()
        st = self.store.get_alert_state(alert_key)
        if st and st.get("active") and st.get("last_fired_at"):
            # 该 key 仍在告警态又被触发：问题没恢复，作废进行中的恢复确认（防抖动击穿）。
            if int(st.get("recover_confirms", 0)) != 0:
                self.store.upsert_alert_state(alert_key, recover_confirms=0)
            elapsed = self._elapsed(st["last_fired_at"], now)
            if elapsed < self.cooldown_seconds:
                return False  # 冷却期内，抑制（recover_confirms 已在上面归零）
        self.store.upsert_alert_state(
            alert_key, last_fired_at=now, active=1, recover_confirms=0
        )
        self._deliver(f"🔴 [{alert_key}] {message}")
        return True

    def resolve(self, alert_key: str, *, now: str | None = None) -> bool:
        """检测恢复。连续 recovery_confirmations 次调用才发"已恢复"。返回本次是否发了恢复。"""
        now = now or tm.now_iso()
        st = self.store.get_alert_state(alert_key)
        if not st or not st.get("active"):
            return False  # 本就不在告警态，无需恢复
        confirms = int(st.get("recover_confirms", 0)) + 1
        if confirms < self.recovery_confirmations:
            self.store.upsert_alert_state(alert_key, recover_confirms=confirms)
            return False  # 确认次数不够，防抖
        self.store.upsert_alert_state(
            alert_key, active=0, recover_confirms=0, last_recovered_at=now
        )
        self._deliver(f"✅ [{alert_key}] 已恢复")
        return True

    @staticmethod
    def _elapsed(since_iso: str, now_iso_str: str) -> float:
        return (datetime.fromisoformat(now_iso_str) - datetime.fromisoformat(since_iso)).total_seconds()

    def _deliver(self, text: str) -> None:
        """双写：本地日志必落；Telegram best-effort（失败只记日志，不抛）。"""
        # 1) 本地日志必落
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(f"{tm.now_iso()} {text}\n")
            except Exception:
                pass
        # 2) Telegram best-effort
        if self.tg is not None and self.chat_id:
            try:
                self.tg.send_message(self.chat_id, text)
            except Exception:
                if self.log_path is not None:
                    try:
                        with self.log_path.open("a", encoding="utf-8") as f:
                            f.write(f"{tm.now_iso()} [telegram-failed] {text}\n")
                    except Exception:
                        pass
