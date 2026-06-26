# 任务队列告警系统 — 设计规格

- 日期：2026-06-25
- 分支：refactor/core-capability-domains
- 状态：待实现
- 归属：诊断文档「Claude E」任务 2（错误监控/告警）。worker 常驻（任务 1）已完成。

## 目标

补齐「失败有人知道」的运维短板：任务失败、worker 掉线、抓取零产出三类事件能**实时触达人**
（Telegram）并**留痕**（本地日志）。轻量实现，不引入 Sentry/Prometheus 等重型依赖。

## 范围红线（与并行的 A/B/C/D 不冲突）

只动监控/告警/运维相关文件：`core/runtime/`（告警引擎、存储）、`core/pipeline/task_worker.py`
（巡检挂载点）、`apps/api/main.py`（API 侧看门狗 + 只读接口）、`core/runtime/config.py`（配置位）。
**不碰** `core/opportunity/`（A 已改）、`core/generator/`（C 将改）、`feature_extraction*`（B 在改）。
复用但不修改 `core/platforms/telegram/api.py`。

## 决策汇总（brainstorming 已对齐）

- **通道**：Telegram（复用 `TelegramClient.send_message`，core/platforms/telegram/api.py:57）+ 本地日志双写。
- **触发**：worker 维护循环巡检（部分掉线/任务失败/零产出）+ API 侧 asyncio 看门狗兜底（全挂）。
- **防刷屏**：按 alert_key 冷却期去重 + 状态恢复时发「已恢复」（连续 N 次确认防抖）。

## 现状基线（实证，附 file:line）

- `TaskStore` 并发保护唯一入口：`_conn()` + `BEGIN IMMEDIATE` + `PRAGMA busy_timeout=30000`
  （task_store.py:136、247、132）。新表读写必须走 TaskStore 方法，**禁止新开裸 sqlite 连接**。
- `init_schema()` 用 `CREATE TABLE IF NOT EXISTS` 幂等建表 + ALTER 迁移（已验证模式）。
- worker 维护循环 `_run_maintenance` 每 60s 一拍（task_worker.py:335，DEFAULT_MAINTENANCE_INTERVAL=60）。
- **当前无 worker 存活记录**：`heartbeat_task` 只更新 `tasks.locked_until`，`locked_by` 仅在有任务时有值
  —— 撑不起全挂检测，故必须新增独立心跳表。
- **API 当前无 startup 钩子**：只有 `@app.on_event("shutdown")`（main.py:1895），无 startup/lifespan
  —— 看门狗需自己新增启动钩子。

## 架构

```
worker 维护循环(每60s, task_worker._run_maintenance)      API startup 看门狗(每120s, 常驻asyncio)
 ·worker_heartbeat(worker_id) 写自己 last_seen             ·count_active_workers()==0 → workers_all_down
 ·count_active_workers()<expected → workers_partial_down    (worker 全死时唯一还活着的告警源)
 ·扫新 failed 任务 → task_failed:<id>
 ·读最近 crawl report → crawl_zero_output:<date>
         │                                                         │
         └──────────────→ AlertManager.fire(key, msg) ←────────────┘
                           ·alert_state 表去重/冷却/恢复态(持久化, 重启不丢)
                           ·连续 N 次确认才发「已恢复」
                           ├→ Telegram (TelegramClient.send_message)
                           └→ data/runtime/logs/alerts.log
```

**两个存活域互补**：worker 循环报"有 worker 活着就能查"的事件；API 看门狗报"worker 全死自己报不了"
的全挂。两域不重叠、不互相依赖。

## 数据表（共 2 张新表，均进 init_schema 幂等迁移）

```sql
CREATE TABLE IF NOT EXISTS workers (
    worker_id   TEXT PRIMARY KEY,
    last_seen   TEXT NOT NULL,
    started_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_state (
    alert_key         TEXT PRIMARY KEY,   -- "workers_all_down" / "task_failed:<id>" / ...
    last_fired_at     TEXT,
    active            INTEGER NOT NULL DEFAULT 0,   -- 1=当前处于告警态
    recover_confirms  INTEGER NOT NULL DEFAULT 0,   -- 连续检测到恢复的次数
    last_recovered_at TEXT
);
```

## 组件

### 1. TaskStore 新增方法（core/runtime/task_store.py，复用 _conn/BEGIN IMMEDIATE）

- `worker_heartbeat(worker_id, now=None)` —— upsert workers 表 last_seen（首次写 started_at）。
- `count_active_workers(timeout_seconds, now=None) -> int` —— `last_seen > now - timeout` 的 worker 数。
- `list_active_workers(timeout_seconds, now=None) -> list[dict]` —— 供 health/接口展示。
- alert_state 读写：`get_alert_state(key)` / `upsert_alert_state(key, **fields)`（供 AlertManager）。

> 心跳与任务解耦：worker 无论有无任务都写 last_seen，证明"进程活着"而非"在干活"。空闲期不误报全挂。

### 2. AlertManager（core/runtime/alerting.py，纯逻辑可独立测）

```python
class AlertManager:
    def __init__(self, store, *, telegram_client=None, chat_id=None,
                 log_path=None, cooldown_seconds=1800, recovery_confirmations=2): ...

    def fire(self, alert_key: str, message: str, *, now=None) -> bool:
        """触发告警。冷却期内同 key 不重复发；首次/冷却过期才发。返回是否真的发了。"""

    def resolve(self, alert_key: str, *, now=None) -> bool:
        """检测恢复。连续 recovery_confirmations 次调用才发"已恢复"并清告警态。"""

    def _deliver(self, text: str): ...   # 双写：Telegram(best-effort) + 本地日志(必落)
```

- **去重/冷却**：`fire` 读 alert_state，`active==1 且 now-last_fired_at < cooldown` → 跳过；否则发并更新。
- **恢复防抖**：`resolve` 每次把 recover_confirms+1；达到 `recovery_confirmations` 才发「已恢复」、
  清 active=0、重置 confirms。未达阈值不发（避免抖动刷屏）。`fire` 重新触发时 recover_confirms 归零。
- **双写容错**：本地日志必落（open-append，不依赖网络）；Telegram best-effort，
  `TelegramAPIError` 吞掉只记日志，不让告警发送失败反过来打断巡检。
- **未配置 Telegram**：chat_id/token 缺失时只写日志，不报错（优雅降级）。

### 3. worker 巡检挂载（core/pipeline/task_worker.py，_run_maintenance 内）

紧挨现有 stale 回收之后，加 `_run_alert_checks()`（整体 try/except，失败不拖垮维护）：
- `store.worker_heartbeat(self.worker_id)` —— 每拍写心跳。
- 部分掉线：`active = count_active_workers(WORKER_TIMEOUT)`；`0 < active < EXPECTED` →
  `alert.fire("workers_partial_down", ...)`；`active >= EXPECTED` → `alert.resolve("workers_partial_down")`。
- 任务失败：查 `list_tasks(status=failed)` 中 finished_at 晚于上次巡检的新失败 →
  `alert.fire(f"task_failed:{tid}", ...)`（每个失败任务一个 key，天然不重复）。
- 抓取零产出：读最近 crawl report 的 `counts.queue_pending`，为 0 →
  `alert.fire(f"crawl_zero_output:{date}", ...)`。

### 4. API 看门狗（apps/api/main.py，新增 startup 钩子）

**API 当前无 startup 钩子，需新增**：

```python
_alert_watchdog_started = False   # 幂等 guard：--reload 热重载会重复触发 startup

@app.on_event("startup")
async def _start_alert_watchdog():
    global _alert_watchdog_started
    if _alert_watchdog_started:        # 防 uvicorn --reload 重复创建看门狗
        return
    _alert_watchdog_started = True
    asyncio.create_task(_alert_watchdog_loop())

async def _alert_watchdog_loop():
    while True:
        await asyncio.sleep(ALERT_API_POLL_SECONDS)   # 默认 120s
        try:
            active = _task_store().count_active_workers(WORKER_TIMEOUT)
            mgr = _alert_manager()
            if active == 0:
                mgr.fire("workers_all_down", "所有 worker 掉线")
            else:
                mgr.resolve("workers_all_down")
        except Exception:
            pass   # 看门狗自身绝不崩
```

- **只管全挂**（active==0）；部分掉线/失败/零产出由 worker 循环管，不重叠。
- **不靠请求触发**：startup 注册常驻 asyncio 循环，半夜无人访问也照跑。
- **多 API worker（uvicorn --workers N）**：N 个看门狗由 AlertManager 冷却去重天然收敛，同 key 冷却期内只发一次。

### 5. 只读接口 + 配置

- `GET /api/alerts`（受 verify_api_key 保护）：读 alert_state + 最近 alerts.log 尾部，供前端/排查。
- 配置位（core/runtime/config.py）：
  `ALERT_TELEGRAM_CHAT_ID`、`ALERT_COOLDOWN_SECONDS`（默认 1800）、`ALERT_EXPECTED_WORKERS`（默认 2）、
  `ALERT_WORKER_TIMEOUT_SECONDS`（默认 150，约 2.5 拍）、`ALERT_API_POLL_SECONDS`（默认 120）、
  `ALERT_RECOVERY_CONFIRMATIONS`（默认 2）。复用现有 `TELEGRAM_BOT_TOKEN`。

## 测试策略

- `core/runtime/tests/test_alerting.py`：AlertManager 纯逻辑——首次发/冷却内不发/冷却过期再发/
  恢复需连续 N 次确认/抖动不刷屏/Telegram 失败仍落日志/未配置优雅降级（注入假 store + 假 client + tmp log）。
- `core/runtime/tests/test_task_store.py`：worker_heartbeat upsert、count_active_workers 超时边界、
  空闲期（无任务）心跳仍在、alert_state 读写持久化。
- `core/pipeline/tests/test_task_worker.py`：_run_alert_checks 调用心跳 + 部分掉线触发/恢复（monkeypatch）。
- `apps/api/tests/test_task_endpoints.py`：/api/alerts 鉴权与返回；看门狗 guard 幂等（重复 startup 只一个 task）。
- 验收：`.venv/bin/python -m pytest core/ apps/api/tests/ -q` 全绿。

## 风险与回滚

| 风险 | 缓解 | 回滚 |
|------|------|------|
| 新表跨进程读写 database is locked | 复用 _conn + BEGIN IMMEDIATE + busy_timeout，禁裸连接 | 删表，无读依赖 |
| 看门狗随 --reload 重复创建 | _alert_watchdog_started 幂等 guard | 移除 startup 钩子 |
| Telegram 发送失败打断巡检 | best-effort 吞异常，日志必落 | AlertManager 可整体停用 |
| 告警刷屏 | 冷却去重 + 恢复连续 N 次确认防抖 | 调大 cooldown |
| 看门狗自身异常 | 循环体 try/except 全包 | — |

