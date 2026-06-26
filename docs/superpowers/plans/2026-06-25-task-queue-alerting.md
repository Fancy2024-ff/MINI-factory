# 任务队列告警系统 — 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 任务失败 / worker 掉线 / 抓取零产出三类事件实时触达人（Telegram）并留痕（本地日志），轻量、不引重型依赖。

**架构：** 独立 `workers` 心跳表撑起存活判定（与任务解耦，空闲不误报）；`AlertManager` 纯逻辑做去重/冷却/恢复防抖 + Telegram/本地日志双写；worker 维护循环巡检"部分掉线/失败/零产出"，API startup 常驻 asyncio 看门狗兜底"全挂"。两个存活域互补。

**技术栈：** Python 标准库 sqlite3（复用 TaskStore 并发保护）、pytest、FastAPI（startup 钩子 + asyncio）、复用 `core/platforms/telegram/api.py`。

**规格来源：** `docs/superpowers/specs/2026-06-25-task-queue-alerting-design.md`

---

## 文件结构

| 文件 | 职责 | 任务 |
|------|------|------|
| `core/runtime/config.py` | 新增 6 个 ALERT_* 配置位 | A1 |
| `core/runtime/task_store.py` | `workers`/`alert_state` 建表 + 心跳/存活/告警态读写方法 | A2, A3 |
| `core/runtime/tests/test_task_store.py` | 心跳 upsert、存活计数边界、空闲心跳、alert_state 持久化、并发 | A2, A3 |
| `core/runtime/alerting.py` | `AlertManager`：fire/resolve/双写（纯逻辑） | A4 |
| `core/runtime/tests/test_alerting.py` | 冷却去重、恢复防抖、双写容错、降级 | A4 |
| `core/pipeline/task_worker.py` | `_run_maintenance` 内挂 `_run_alert_checks`（心跳+部分掉线+失败+零产出） | A5 |
| `core/pipeline/tests/test_task_worker.py` | 心跳被调、部分掉线触发/恢复 | A5 |
| `apps/api/main.py` | startup 看门狗（全挂兜底 + reload guard）+ `GET /api/alerts` | A6 |
| `apps/api/tests/test_task_endpoints.py` | /api/alerts 鉴权与返回、看门狗 guard 幂等、全挂主链路 | A6 |

**关键默认值（写进 config）：** `ALERT_WORKER_TIMEOUT_SECONDS=180`（心跳 60s 的 3 倍，绝不贴 60s 否则误报）、`ALERT_COOLDOWN_SECONDS=1800`、`ALERT_EXPECTED_WORKERS=2`、`ALERT_API_POLL_SECONDS=120`、`ALERT_RECOVERY_CONFIRMATIONS=2`、`ALERT_TELEGRAM_CHAT_ID=""`。

---

## 任务 A1：告警配置位（config.py）

**文件：**
- 修改：`core/runtime/config.py`（末尾追加 ALERT_* 段）

- [ ] **步骤 1：实现配置位**

在 `core/runtime/config.py` 末尾（第 74 行 `DOUYIN_APPID` 之后）追加：

```python

# ── 告警系统（Claude E 任务 2）──────────────────────────────────
# 告警发往的 Telegram chat（复用 TELEGRAM_BOT_TOKEN）。空 = 只写本地日志，不发 TG。
ALERT_TELEGRAM_CHAT_ID = os.getenv("ALERT_TELEGRAM_CHAT_ID", "")
# 同一 alert_key 冷却期（秒）：冷却期内同类告警不重复发。
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "1800"))
# 期望常驻 worker 数：active < 此值 → 部分掉线告警。
ALERT_EXPECTED_WORKERS = int(os.getenv("ALERT_EXPECTED_WORKERS", "2"))
# worker 掉线判定超时（秒）：last_seen 早于 now-该值 视为掉线。
# 必须 >> 心跳间隔(60s)，取 3 倍=180，避免"还没到下一个心跳点"被误判掉线。
ALERT_WORKER_TIMEOUT_SECONDS = int(os.getenv("ALERT_WORKER_TIMEOUT_SECONDS", "180"))
# API 看门狗轮询间隔（秒）：兜底检测"全部 worker 掉线"。
ALERT_API_POLL_SECONDS = int(os.getenv("ALERT_API_POLL_SECONDS", "120"))
# 恢复确认次数：连续 N 次检测到恢复才发"已恢复"，防抖动刷屏。
ALERT_RECOVERY_CONFIRMATIONS = int(os.getenv("ALERT_RECOVERY_CONFIRMATIONS", "2"))
```

- [ ] **步骤 2：验证可导入且默认值正确**

运行：`.venv/bin/python -c "from core.runtime import config as c; assert c.ALERT_WORKER_TIMEOUT_SECONDS==180 and c.ALERT_EXPECTED_WORKERS==2 and c.ALERT_RECOVERY_CONFIRMATIONS==2; print('config ok')"`
预期：`config ok`

- [ ] **步骤 3：Commit**

```bash
git add core/runtime/config.py
git commit -m "feat(config): 告警系统配置位(worker_timeout=180 防误报)(A1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A2：workers 心跳表 + 存活判定

**文件：**
- 修改：`core/runtime/task_store.py`（`_SCHEMA` 加表；新增 `worker_heartbeat`/`count_active_workers`/`list_active_workers`）
- 测试：`core/runtime/tests/test_task_store.py`

- [ ] **步骤 1：编写失败的测试**

在 `core/runtime/tests/test_task_store.py` 末尾追加：

```python
# --- 告警 A2: workers 心跳表 ---

def test_worker_heartbeat_upsert(store):
    store.worker_heartbeat("w1")
    rows = store.list_active_workers(180)
    assert len(rows) == 1 and rows[0]["worker_id"] == "w1"
    # 再次心跳：仍是一行（upsert，不新增）
    store.worker_heartbeat("w1")
    assert len(store.list_active_workers(180)) == 1


def test_count_active_workers_timeout_boundary(store):
    from core.runtime.task_store import _add_seconds
    now = now_iso()
    store.worker_heartbeat("w1", now=_add_seconds(now, -200))  # 200s 前，超 180 超时
    store.worker_heartbeat("w2", now=_add_seconds(now, -10))   # 10s 前，活
    assert store.count_active_workers(180, now=now) == 1       # 只 w2 算活


def test_count_active_workers_idle_still_alive(store):
    """队列无任何任务时，worker 心跳仍使其被计为 active（心跳与任务解耦，空闲不误报）。"""
    store.worker_heartbeat("w1")
    store.worker_heartbeat("w2")
    # 没有 enqueue 任何任务
    assert store.count_active_workers(180) == 2


def test_count_active_workers_concurrent_read_write(tmp_path):
    """worker 写心跳 + 并发读 workers 表，不 database-locked。"""
    import threading
    store = TaskStore(tmp_path / "tasks.sqlite3")
    errors = []

    def beat(wid):
        try:
            for _ in range(20):
                store.worker_heartbeat(wid)
        except Exception as e:
            errors.append(e)

    def read():
        try:
            for _ in range(20):
                store.count_active_workers(180)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=beat, args=("w1",)),
               threading.Thread(target=beat, args=("w2",)),
               threading.Thread(target=read)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []  # 无 database is locked
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/runtime/tests/test_task_store.py -k "worker_heartbeat or count_active" -v`
预期：FAIL，`AttributeError: 'TaskStore' object has no attribute 'worker_heartbeat'`

- [ ] **步骤 3a：加表到 _SCHEMA**

在 `core/runtime/task_store.py` 的 `_SCHEMA` 内（`queue_maintenance` 建表之后、闭合 `"""` 之前）追加：

```sql

CREATE TABLE IF NOT EXISTS workers (
    worker_id   TEXT PRIMARY KEY,
    last_seen   TEXT NOT NULL,
    started_at  TEXT NOT NULL
);
```

- [ ] **步骤 3b：加方法（紧跟 try_acquire_maintenance 之后）**

```python
    def worker_heartbeat(self, worker_id: str, now: str | None = None) -> None:
        """worker 心跳：upsert 自己的 last_seen。无论有无任务都调，证明进程活着。"""
        now = now or tm.now_iso()
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO workers (worker_id, last_seen, started_at)
                VALUES (?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (worker_id, now, now),
            )
        finally:
            self._close(conn)

    def list_active_workers(self, timeout_seconds: int, now: str | None = None) -> list[dict]:
        """last_seen 在 now-timeout 之内的 worker（视为存活）。"""
        now = now or tm.now_iso()
        threshold = _add_seconds(now, -timeout_seconds)
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT worker_id, last_seen, started_at FROM workers WHERE last_seen > ?",
                (threshold,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close(conn)

    def count_active_workers(self, timeout_seconds: int, now: str | None = None) -> int:
        """存活 worker 数（last_seen > now-timeout）。"""
        return len(self.list_active_workers(timeout_seconds, now=now))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/runtime/tests/test_task_store.py -k "worker_heartbeat or count_active" -v`
预期：4 PASS。

- [ ] **步骤 5：Commit**

```bash
git add core/runtime/task_store.py core/runtime/tests/test_task_store.py
git commit -m "feat(task-store): workers 心跳表+存活判定(心跳与任务解耦)(A2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A3：alert_state 表 + 读写方法（去重/恢复态持久化）

**文件：**
- 修改：`core/runtime/task_store.py`（`_SCHEMA` 加表；新增 `get_alert_state`/`upsert_alert_state`）
- 测试：`core/runtime/tests/test_task_store.py`

- [ ] **步骤 1：编写失败的测试**

在 `core/runtime/tests/test_task_store.py` 末尾追加：

```python
# --- 告警 A3: alert_state 持久化 ---

def test_alert_state_absent_returns_none(store):
    assert store.get_alert_state("nope") is None


def test_alert_state_upsert_and_read(store):
    store.upsert_alert_state("workers_all_down", last_fired_at="2026-06-25T10:00:00+00:00",
                             active=1, recover_confirms=0)
    s = store.get_alert_state("workers_all_down")
    assert s["active"] == 1 and s["last_fired_at"] == "2026-06-25T10:00:00+00:00"
    # 部分更新：只改 recover_confirms，其它字段保留
    store.upsert_alert_state("workers_all_down", recover_confirms=2)
    s2 = store.get_alert_state("workers_all_down")
    assert s2["recover_confirms"] == 2 and s2["active"] == 1


def test_alert_state_persists_across_store_reopen(tmp_path):
    """重启不丢：新建 store 实例读到同一库的 alert_state（进程重启不重复告警）。"""
    db = tmp_path / "tasks.sqlite3"
    s1 = TaskStore(db)
    s1.upsert_alert_state("k1", active=1, last_fired_at="2026-06-25T10:00:00+00:00")
    s2 = TaskStore(db)  # 模拟重启
    assert s2.get_alert_state("k1")["active"] == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/runtime/tests/test_task_store.py -k alert_state -v`
预期：FAIL，`AttributeError: ... 'get_alert_state'`

- [ ] **步骤 3a：加表到 _SCHEMA**

在 `_SCHEMA` 内 `workers` 表之后、闭合 `"""` 之前追加：

```sql

CREATE TABLE IF NOT EXISTS alert_state (
    alert_key         TEXT PRIMARY KEY,
    last_fired_at     TEXT,
    active            INTEGER NOT NULL DEFAULT 0,
    recover_confirms  INTEGER NOT NULL DEFAULT 0,
    last_recovered_at TEXT
);
```

- [ ] **步骤 3b：加方法（紧跟 count_active_workers 之后）**

```python
    def get_alert_state(self, alert_key: str) -> dict | None:
        """读告警状态行；不存在返回 None。"""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM alert_state WHERE alert_key = ?", (alert_key,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            self._close(conn)

    def upsert_alert_state(self, alert_key: str, **fields) -> None:
        """插入/部分更新告警状态。只更新传入的字段（其余保留原值）。

        允许字段：last_fired_at / active / recover_confirms / last_recovered_at。
        """
        allowed = {"last_fired_at", "active", "recover_confirms", "last_recovered_at"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown alert_state fields: {bad}")
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM alert_state WHERE alert_key = ?", (alert_key,)
            ).fetchone()
            if exists is None:
                conn.execute(
                    "INSERT INTO alert_state (alert_key, active, recover_confirms) VALUES (?, 0, 0)",
                    (alert_key,),
                )
            if fields:
                cols = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE alert_state SET {cols} WHERE alert_key = ?",
                    (*fields.values(), alert_key),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._close(conn)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/runtime/tests/test_task_store.py -k alert_state -v`
预期：3 PASS。再跑全量 store：`.venv/bin/python -m pytest core/runtime/tests/test_task_store.py -q` 全绿。

- [ ] **步骤 5：Commit**

```bash
git add core/runtime/task_store.py core/runtime/tests/test_task_store.py
git commit -m "feat(task-store): alert_state 持久化(去重/恢复态,重启不丢)(A3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A4：AlertManager 核心（去重/冷却/恢复防抖 + 双写）

**文件：**
- 创建：`core/runtime/alerting.py`
- 测试：`core/runtime/tests/test_alerting.py`

- [ ] **步骤 1：编写失败的测试**

创建 `core/runtime/tests/test_alerting.py`：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/runtime/tests/test_alerting.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'core.runtime.alerting'`

- [ ] **步骤 3：实现 AlertManager（见下方完整代码，分块写入）**

创建 `core/runtime/alerting.py`，内容见步骤 3 代码块（A4-impl）。

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/runtime/tests/test_alerting.py -v`
预期：8 PASS。

- [ ] **步骤 5：Commit**

```bash
git add core/runtime/alerting.py core/runtime/tests/test_alerting.py
git commit -m "feat(alerting): AlertManager 去重/冷却/恢复防抖+双写(A4)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### A4-impl：`core/runtime/alerting.py` 完整实现

```python
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
            elapsed = self._elapsed(st["last_fired_at"], now)
            if elapsed < self.cooldown_seconds:
                return False  # 冷却期内，抑制
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
```

---

## 任务 A5：worker 巡检挂载（心跳 + 部分掉线 + 失败 + 零产出）

**文件：**
- 修改：`core/pipeline/task_worker.py`（构造 AlertManager；`_run_maintenance` 末尾调 `_run_alert_checks`；新增该方法）
- 测试：`core/pipeline/tests/test_task_worker.py`

- [ ] **步骤 1：编写失败的测试**

在 `core/pipeline/tests/test_task_worker.py` 末尾追加：

```python
# --- 告警 A5: worker 巡检 ---

def test_alert_checks_writes_heartbeat(store, monkeypatch):
    monkeypatch.setattr(store, "try_acquire_maintenance", lambda *a, **k: True)
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    worker._run_maintenance(force=True)
    # 心跳已写：自己在 active 列表里
    assert store.count_active_workers(180) >= 1


def test_alert_checks_partial_down_fires(store, monkeypatch):
    monkeypatch.setattr(store, "try_acquire_maintenance", lambda *a, **k: True)
    fired = []
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    worker._alert.fire = lambda key, msg, **k: fired.append(key) or True
    worker._alert.resolve = lambda key, **k: False
    # 期望 2 个 worker，但只有自己心跳 → active=1 < 2 → 部分掉线
    monkeypatch.setattr(worker, "_expected_workers", 2)
    worker._run_maintenance(force=True)
    assert "workers_partial_down" in fired


def test_alert_checks_exception_does_not_break(store, monkeypatch):
    monkeypatch.setattr(store, "try_acquire_maintenance", lambda *a, **k: True)
    worker = TaskWorker(store=store, worker_id="w-test", maintenance_interval=60)
    def boom(*a, **k):
        raise RuntimeError("hb fail")
    monkeypatch.setattr(store, "worker_heartbeat", boom)
    worker._run_maintenance(force=True)  # 不抛
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/pipeline/tests/test_task_worker.py -k "alert_checks" -v`
预期：FAIL，`AttributeError: 'TaskWorker' object has no attribute '_alert'`

- [ ] **步骤 3a：构造 AlertManager（修改 __init__，约 task_worker.py:320-329）**

在 `TaskWorker.__init__` 方法体末尾（`self._stop = False` 之后）追加：

```python
        # 告警：从 config 读阈值，复用 TelegramClient（缺 token/chat 时优雅降级）。
        from core.runtime import config as _cfg
        from core.runtime.alerting import AlertManager
        tg = None
        if _cfg.TELEGRAM_BOT_TOKEN and _cfg.ALERT_TELEGRAM_CHAT_ID:
            try:
                from core.platforms.telegram.api import TelegramClient
                tg = TelegramClient(_cfg.TELEGRAM_BOT_TOKEN)
            except Exception:
                tg = None
        self._expected_workers = _cfg.ALERT_EXPECTED_WORKERS
        self._worker_timeout = _cfg.ALERT_WORKER_TIMEOUT_SECONDS
        self._alert = AlertManager(
            self.store, telegram_client=tg, chat_id=_cfg.ALERT_TELEGRAM_CHAT_ID or None,
            log_path=PROJECT_ROOT / "data" / "runtime" / "logs" / "alerts.log",
            cooldown_seconds=_cfg.ALERT_COOLDOWN_SECONDS,
            recovery_confirmations=_cfg.ALERT_RECOVERY_CONFIRMATIONS,
        )
        self._last_failed_scan = tm.now_iso()
```

> `PROJECT_ROOT` 已在 task_worker.py 顶部定义（第 35 行）；需在文件顶部 import 处加 `from core.runtime import task_models as tm`（若尚未导入）。

- [ ] **步骤 3b：_run_maintenance 末尾调用巡检**

在 `_run_maintenance` 的 try 块内，stale 回收 `print(...)` 之后、`except` 之前追加一行：

```python
            self._run_alert_checks()
```

- [ ] **步骤 3c：新增 _run_alert_checks（紧跟 _run_maintenance 之后）**

```python
    def _run_alert_checks(self) -> None:
        """worker 侧告警巡检：心跳 + 部分掉线 + 新失败任务 + 抓取零产出。

        整体 try/except：告警失败绝不拖垮维护。全挂检测由 API 看门狗负责（worker 全死自己报不了）。
        """
        try:
            self.store.worker_heartbeat(self.worker_id)
            # 部分掉线：0 < active < expected。active==0 留给 API 看门狗（这里 worker 自己活着，不会是 0）。
            active = self.store.count_active_workers(self._worker_timeout)
            if 0 < active < self._expected_workers:
                self._alert.fire("workers_partial_down",
                                 f"worker 在线 {active}/{self._expected_workers}")
            elif active >= self._expected_workers:
                self._alert.resolve("workers_partial_down")
            # 新失败任务：finished_at 晚于上次扫描的 failed。
            scan_from = self._last_failed_scan
            self._last_failed_scan = tm.now_iso()
            for t in self.store.list_tasks(status="failed", limit=50):
                fin = t.get("finished_at") or ""
                if fin > scan_from:
                    self._alert.fire(f"task_failed:{t['id']}",
                                     f"任务失败 kind={t.get('kind')} code={t.get('error_code')}")
            # 抓取零产出：读 crawl-report.json 的 counts.queue_pending（纯读数据文件，不 import 抓取代码）。
            self._check_crawl_zero_output()
        except Exception as e:  # noqa: BLE001
            print(f"[worker {self.worker_id}] alert check error: {e}", flush=True)

    def _check_crawl_zero_output(self) -> None:
        """读最近 crawl-report，queue_pending==0 则告警（按日期 key 去重）。"""
        import json
        report_path = PROJECT_ROOT / "data" / "opportunity" / "crawl-report.json"
        if not report_path.exists():
            return
        try:
            rep = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        counts = rep.get("counts") or {}
        date = rep.get("date") or "unknown"
        if counts.get("queue_pending", -1) == 0:
            self._alert.fire(f"crawl_zero_output:{date}", f"抓取 {date} 零产出（queue_pending=0）")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/pipeline/tests/test_task_worker.py -v`
预期：新增 3 个 PASS，现有用例（heartbeat/stale/cancel 等）保持绿。

- [ ] **步骤 5：Commit**

```bash
git add core/pipeline/task_worker.py core/pipeline/tests/test_task_worker.py
git commit -m "feat(task-worker): 巡检挂载-心跳/部分掉线/失败/零产出告警(A5)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A6：API 看门狗（全挂兜底 + reload guard）+ /api/alerts

**文件：**
- 修改：`apps/api/main.py`（新增 startup 钩子 + 看门狗循环 + AlertManager 构造器 + `GET /api/alerts`）
- 测试：`apps/api/tests/test_task_endpoints.py`

- [ ] **步骤 1：编写失败的测试**

在 `apps/api/tests/test_task_endpoints.py` 末尾追加：

```python
# --- 告警 A6: API 看门狗 + /api/alerts ---

def test_alerts_endpoint_requires_key(server_client):
    client, _ = server_client
    assert client.get("/api/alerts").status_code == 401


def test_alerts_endpoint_returns_state(server_client, auth_headers):
    client, api = server_client
    # 写一条告警态
    api._task_store().upsert_alert_state("workers_all_down", active=1,
                                         last_fired_at="2026-06-25T10:00:00+00:00")
    res = client.get("/api/alerts", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert any(a["alert_key"] == "workers_all_down" for a in body["alerts"])


def test_watchdog_full_down_main_chain(server_client):
    """全挂主链路：active==0 → 看门狗 fire workers_all_down。"""
    client, api = server_client
    store = api._task_store()
    # 没有任何 worker 心跳 → active==0
    assert store.count_active_workers(180) == 0
    fired = []
    mgr = api._alert_manager()
    mgr.fire = lambda key, msg, **k: fired.append(key) or True
    mgr.resolve = lambda key, **k: False
    # 直接驱动看门狗单拍逻辑（不等真实 sleep）
    api._watchdog_tick()
    assert "workers_all_down" in fired


def test_watchdog_not_full_down_resolves(server_client):
    client, api = server_client
    store = api._task_store()
    store.worker_heartbeat("w1")  # 有 worker 活着
    calls = {"fire": [], "resolve": []}
    mgr = api._alert_manager()
    mgr.fire = lambda key, msg, **k: calls["fire"].append(key) or True
    mgr.resolve = lambda key, **k: calls["resolve"].append(key) or True
    api._watchdog_tick()
    assert "workers_all_down" not in calls["fire"]
    assert "workers_all_down" in calls["resolve"]


def test_watchdog_guard_idempotent(server_client):
    """startup 重复触发（--reload）只起一个看门狗 task。"""
    client, api = server_client
    api._alert_watchdog_started = False
    import asyncio
    async def run_twice():
        await api._start_alert_watchdog()
        first = api._alert_watchdog_started
        await api._start_alert_watchdog()  # 第二次应被 guard 拦
        return first and api._alert_watchdog_started
    assert asyncio.get_event_loop().run_until_complete(run_twice()) is True
```

> `auth_headers` fixture 已存在于 conftest；若无则用 `{"x-api-key": "secret123"}`。

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest apps/api/tests/test_task_endpoints.py -k "alerts_endpoint or watchdog" -v`
预期：FAIL（接口 404 / `_alert_manager` 不存在）。

- [ ] **步骤 3a：AlertManager 构造器（紧跟 main.py 的 `_task_store()` 之后，约第 947 行）**

```python
_alert_manager_instance = None


def _alert_manager():
    """惰性构建 API 侧 AlertManager 单例（复用 _task_store + config）。"""
    global _alert_manager_instance
    if _alert_manager_instance is None:
        from core.runtime import config as cfg
        from core.runtime.alerting import AlertManager
        from pathlib import Path
        tg = None
        if cfg.TELEGRAM_BOT_TOKEN and cfg.ALERT_TELEGRAM_CHAT_ID:
            try:
                from core.platforms.telegram.api import TelegramClient
                tg = TelegramClient(cfg.TELEGRAM_BOT_TOKEN)
            except Exception:
                tg = None
        _alert_manager_instance = AlertManager(
            _task_store(), telegram_client=tg,
            chat_id=cfg.ALERT_TELEGRAM_CHAT_ID or None,
            log_path=Path(__file__).resolve().parents[2] / "data" / "runtime" / "logs" / "alerts.log",
            cooldown_seconds=cfg.ALERT_COOLDOWN_SECONDS,
            recovery_confirmations=cfg.ALERT_RECOVERY_CONFIRMATIONS,
        )
    return _alert_manager_instance
```

- [ ] **步骤 3b：看门狗单拍 + 循环 + startup 钩子（接在上一段之后）**

```python
def _watchdog_tick():
    """看门狗单拍：仅检测"全部 worker 掉线"（worker 自己报不了，由 API 兜底）。"""
    from core.runtime import config as cfg
    active = _task_store().count_active_workers(cfg.ALERT_WORKER_TIMEOUT_SECONDS)
    mgr = _alert_manager()
    if active == 0:
        mgr.fire("workers_all_down", "所有 worker 掉线（API 看门狗检测）")
    else:
        mgr.resolve("workers_all_down")


_alert_watchdog_started = False


async def _alert_watchdog_loop():
    from core.runtime import config as cfg
    while True:
        await asyncio.sleep(cfg.ALERT_API_POLL_SECONDS)
        try:
            _watchdog_tick()
        except Exception:
            pass  # 看门狗自身绝不崩


@app.on_event("startup")
async def _start_alert_watchdog():
    """注册常驻看门狗。reload guard 防 uvicorn --reload 重复创建。"""
    global _alert_watchdog_started
    if _alert_watchdog_started:
        return
    _alert_watchdog_started = True
    asyncio.create_task(_alert_watchdog_loop())
```

- [ ] **步骤 3c：只读接口 GET /api/alerts（接在 /api/tasks/health 附近）**

```python
@app.get("/api/alerts", dependencies=[Depends(verify_api_key)])
def list_alerts():
    """读当前告警态（alert_state 全表）+ 最近告警日志尾部，供排查。"""
    from pathlib import Path
    store = _task_store()
    conn = store._conn()
    try:
        rows = conn.execute("SELECT * FROM alert_state ORDER BY last_fired_at DESC").fetchall()
        alerts = [dict(r) for r in rows]
    finally:
        store._close(conn)
    log_tail = []
    log_path = Path(__file__).resolve().parents[2] / "data" / "runtime" / "logs" / "alerts.log"
    if log_path.exists():
        log_tail = log_path.read_text(encoding="utf-8").splitlines()[-50:]
    return {"alerts": alerts, "log_tail": log_tail}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest apps/api/tests/test_task_endpoints.py -k "alerts_endpoint or watchdog" -v`
预期：5 PASS。

- [ ] **步骤 5：Commit**

```bash
git add apps/api/main.py apps/api/tests/test_task_endpoints.py
git commit -m "feat(api): 看门狗全挂兜底(startup+reload guard)+/api/alerts(A6)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务 A7：全量回归 + 6 条底线验收

不写新逻辑，统一验证规格要求的底线场景全绿。

- [ ] **步骤 1：底线场景逐项确认**

运行：`.venv/bin/python -m pytest core/ apps/api/tests/ -q`，确认以下底线测试存在且通过：
- 全挂主链路 → `test_task_endpoints.py::test_watchdog_full_down_main_chain`
- 空闲不误报 → `test_task_store.py::test_count_active_workers_idle_still_alive`
- 恢复防抖 → `test_alerting.py::test_resolve_requires_consecutive_confirmations` + `test_resolve_jitter_does_not_emit`
- 重启不丢状态 → `test_task_store.py::test_alert_state_persists_across_store_reopen`
- 并发不锁 → `test_task_store.py::test_count_active_workers_concurrent_read_write`
- reload guard → `test_task_endpoints.py::test_watchdog_guard_idempotent`

- [ ] **步骤 2：前端无回归**

运行：`cd apps/web && npm test`
预期：全绿（本计划未改前端，应不受影响）。

- [ ] **步骤 3：更新规格状态 + Commit**

把 `docs/superpowers/specs/2026-06-25-task-queue-alerting-design.md` 头部状态改为 `已实现`。

```bash
git add docs/superpowers/specs/2026-06-25-task-queue-alerting-design.md
git commit -m "docs(design): 标记告警系统已实现(A7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 自检结果

**规格覆盖度：**
- Telegram+本地日志双写 → A4（`_deliver`）✅
- worker 心跳表/存活判定（空闲不误报）→ A2 ✅
- alert_state 持久化（重启不丢）→ A3 ✅
- AlertManager 去重/冷却/恢复防抖 → A4 ✅
- worker 巡检（部分掉线/失败/零产出）→ A5 ✅
- API 看门狗全挂兜底 + startup 钩子 + reload guard → A6 ✅
- /api/alerts 只读接口 → A6 ✅
- 配置默认值（worker_timeout=180）→ A1 ✅
- 6 条底线测试 → 分散在 A2/A4/A6，A7 汇总 ✅

**占位符扫描：** 无 TODO/待定。A4 实现代码完整给出（A4-impl 块），非"后续实现"。

**类型一致性：** `worker_heartbeat`/`count_active_workers`/`list_active_workers`（A2 定义 → A5/A6 调用）签名一致；`get_alert_state`/`upsert_alert_state`（A3 定义 → A4 调用）一致；`AlertManager(store, telegram_client, chat_id, log_path, cooldown_seconds, recovery_confirmations)` 构造签名在 A4 定义、A5/A6 调用处完全一致；`fire(key, msg, now=)`/`resolve(key, now=)` 签名统一；`_watchdog_tick`/`_alert_manager`/`_alert_watchdog_started`（A6 内部自洽）。

**红线检查：** 所有改动文件在 `core/runtime/`、`core/pipeline/task_worker.py`、`apps/api/main.py`、`config.py`；`_check_crawl_zero_output` 只读 `data/opportunity/crawl-report.json` 数据文件，不 import `core/opportunity/` 代码。未碰 A/B/C 红线。





