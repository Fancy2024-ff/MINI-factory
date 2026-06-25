# 任务队列稳定可运维化改造 — 设计规格

- 日期：2026-06-25
- 分支：refactor/core-capability-domains
- 状态：待实现（A 阶段先行，B 阶段仅计划）

## 目标

把任务队列从「能跑」升级到「稳定可运维」。**第一阶段（A）只做直接影响稳定性的能力**，
不做大范围调度算法重构。第二阶段（B）只写计划，不实现，待 A 完成并评估后再启动。

非目标（明确不做）：
- 不重写 `task_store.py` / `task_worker.py` 的核心模型，只做增量增强。
- 不引入 Redis / Postgres，继续 SQLite + WAL。
- 不在 A 阶段引入有效优先级 SQL（优先级老化推到 B）。
- 不在 A 阶段做 DB 记录清理（TTL 推到 B，且永不碰 pending/running）。

## 硬约束（贯穿所有任务）

1. 不重写核心模型，只增量增强。
2. 不引入 Redis/Postgres。
3. 不破坏现有 API 兼容性（现有字段只增不改不删）。
4. 不影响现有 generate_now / cancel / retry 行为。
5. cleanup 类逻辑永不触碰 pending/running，只允许终态（succeeded/failed/cancelled）。
6. `deploy/launchd` 和 `deploy/systemd` 是配置层，平台差异不写进业务代码。
7. 每个任务 TDD：测试先行，或至少同 commit 带测试。
8. 每个任务独立 commit。
9. A 阶段完成后再评估 B，不一次性全做。

## 现状基线（改造前）

- 存储层 `core/runtime/task_store.py`：SQLite + WAL，`claim_next_task` 用 `BEGIN IMMEDIATE`
  写事务串行化，已保证并发安全。已有 `requeue_stale_tasks_detailed()`、`find_active_by_queue_id()`。
- 执行层 `core/pipeline/task_worker.py`：`TaskWorker.run()` 串行消费，已有 heartbeat 续租、
  cancel 感知、子进程监督。**但无自动 stale 回收、无常驻进程管理、从未起过多 worker。**
- API 层 `apps/api/main.py`：已有 `/api/tasks/summary`、`/api/tasks`、cancel/retry 等接口。
- 前端 `apps/web/src/components/TaskQueuePanel.vue`：展示状态计数。
- 现有测试：`core/runtime/tests/test_task_store.py`、`core/pipeline/tests/test_task_worker.py`、
  `apps/api/tests/test_task_endpoints.py`、`apps/api/tests/test_queue_action_endpoint.py`。

## 架构总览

```
A 阶段改动落点
─────────────────────────────────────────────────────────────
core/runtime/task_store.py     +health_summary()  +maintenance lock(last_run)
core/pipeline/task_worker.py   +启动时/周期 stale 回收  +maintenance_interval
apps/api/main.py               +GET /api/tasks/health
apps/web/.../TaskQueuePanel.vue +“队列健康”一行展示
deploy/launchd/*.plist         (新增，Mac 常驻)
deploy/systemd/*.service       (新增，Linux 常驻)
deploy/README.md               (新增，启动/运维说明)
```

设计原则：业务逻辑进 store/worker 层并配测试；进程管理用配置文件，不改业务代码。
Mac→服务器迁移时业务代码零改动，只换进程管理器。

## 维护锁机制（多 worker 防重复维护）

多 worker 时，stale 回收 / 维护动作不能每个 worker 都各跑一遍。方案：在 `tasks` 同库新增
一张极简表 `queue_maintenance`，单行记录 `last_run_at`。worker 在维护时刻用一次
`BEGIN IMMEDIATE` 写事务 CAS 抢占：

```
UPDATE queue_maintenance
SET last_run_at = :now, runner = :worker_id
WHERE name = 'stale_recovery' AND (last_run_at IS NULL OR last_run_at <= :now - interval)
```

`rowcount > 0` 的 worker 才执行实际回收，其余跳过。复用现有 `BEGIN IMMEDIATE` 串行化保证，
不引入新依赖。这是「轻量 last_run + 抢占」机制，满足约束要求。

## A 阶段任务列表

### A1 — 维护锁机制（queue_maintenance 表 + CAS 抢占）
先做，因为 A2 的周期回收依赖它防多 worker 竞争。

- 改动文件：`core/runtime/task_store.py`（新增 `queue_maintenance` 建表 + `try_acquire_maintenance(name, interval, worker_id, now)` 方法）
- 测试文件：`core/runtime/tests/test_task_store.py`（新增 `test_maintenance_lock_*`）
- 验收标准：
  - 表在 `init_schema()` 幂等创建（旧库自动迁移，无报错）。
  - 首次调用 `try_acquire_maintenance` 返回 True；interval 内再调返回 False；超过 interval 后返回 True。
  - 两个 worker_id 在同一时刻并发调用，只有一个返回 True（并发安全，线程测试）。
- 风险：旧库迁移失败 → 用 `CREATE TABLE IF NOT EXISTS` + try/except OperationalError 兜底（与现有 _MIGRATIONS 同模式）。
- 回滚：删除新增方法与表 DDL；表存在不影响旧逻辑（无外键、无读依赖）。

### A2 — worker 内 stale 自动回收
- 改动文件：`core/pipeline/task_worker.py`（`TaskWorker.__init__` 加 `maintenance_interval`；
  `run()` 启动时先跑一次 stale recovery，主循环按 interval + A1 维护锁周期跑；新增 `_run_maintenance()`）
- 测试文件：`core/pipeline/tests/test_task_worker.py`（新增 `test_stale_recovery_on_startup`、
  `test_maintenance_runs_periodically`、`test_long_task_not_requeued_while_heartbeat_alive` 已存在需保持通过）
- 验收标准：
  - worker 启动（run 开始）先调一次 `requeue_stale_tasks_detailed()`。
  - 主循环每 `maintenance_interval`（默认 60s）经维护锁尝试一次回收。
  - stale recovery 只影响 `locked_until` 已过期的 running task，不碰 fresh running / pending（复用现有 SQL，已有测试 `test_stale_requeue_does_not_touch_fresh_lock`）。
  - 长任务 heartbeat 存活期间不被误回收（现有测试保持绿）。
- 风险：维护逻辑异常拖垮消费循环 → `_run_maintenance()` 整体 try/except 吞异常并继续。
- 回滚：移除 run() 中维护调用，worker 退回纯消费（行为等同改造前）。

### A3 — 多 worker 并发（验证 + 配置，不改 claim 核心）
- 改动文件：无核心逻辑改动（`claim_next_task` 已并发安全）；
  `deploy/` 配置支持起 N 个；`docs/operation/RUNBOOK.md` 补多 worker 说明。
- 测试文件：`core/runtime/tests/test_task_store.py`（强化 `test_concurrent_claim_no_duplicate` 多线程版）
- 验收标准：
  - 多线程并发 claim N 个任务，无任何 task 被两个 worker 同时 claim（每个 task 恰好一次）。
  - 同 `queue_id` 已有 active task 时，`find_active_by_queue_id` 去重生效，不重复入队执行
    （现有 `enqueue_pipeline_task` dedupe 逻辑保持，补测试断言）。
  - 默认 worker 数 2，可配置到 4（deploy 配置层体现）。
- 风险：SQLite 写锁竞争 → WAL + busy_timeout 已配；文档注明 2~4 为建议上限。
- 回滚：起单 worker 即退回原行为。

### A4 — 最小健康指标
- 改动文件：`core/runtime/task_store.py`（新增 `health_summary()`）；
  `apps/api/main.py`（新增 `GET /api/tasks/health`）；
  `apps/web/src/components/TaskQueuePanel.vue`（加“队列健康”一行）；
  `apps/web/src/types/job.ts`（加 health 类型）
- 测试文件：`core/runtime/tests/test_task_store.py`（`test_health_summary_*`）；
  `apps/api/tests/test_task_endpoints.py`（`test_tasks_health_endpoint`）；
  `apps/web/src/__tests__/taskQueueViews.test.ts`（health 展示）
- `/api/tasks/health` 返回字段（至少）：
  `total, pending, running, succeeded, failed, cancelled, oldest_pending_seconds,
  running_count, active_worker_count`。
  - `oldest_pending_seconds`：最老 pending 的等待秒数（无 pending 则 0/null）。
  - `active_worker_count`：近似指标 = 近 `lock_seconds` 内有 heartbeat（locked_until 未过期）
    的不同 locked_by 数。
- 验收标准：
  - 空库返回全 0，不报错。
  - 构造 pending/running 数据后字段数值正确（含 oldest_pending_seconds 单调性）。
  - 接口受 `verify_api_key` 保护，与现有 task 接口一致。
  - 前端只增一行展示，不大改 UI；现有面板测试保持绿。
- 风险：聚合查询性能 → 数据量小（MVP），单查询可接受；加 created_at 索引已存在。
- 回滚：移除接口与方法；前端隐藏该行。

### A5 — 常驻 worker 进程管理（launchd + systemd）
- 改动文件（全部新增，配置层）：
  - `deploy/launchd/com.minifactory.worker.plist`（Mac，KeepAlive 自动重启、开机自启、日志重定向）
  - `deploy/systemd/minifactory-worker@.service`（Linux 模板单元，Restart=always）
  - `deploy/README.md`（安装/启动/查看日志/起多 worker 命令）
- 共用启动命令：`python -m core.pipeline.task_worker --worker-id <id>`（两平台一致）。
- 日志：写到 `data/runtime/logs/`（launchd StandardOut/ErrorPath；systemd 用 journal 或重定向）。
- 验收标准：
  - 两套配置共用同一条 worker 启动命令，仅进程管理器不同。
  - 配置中 worker 崩溃自动重启（KeepAlive / Restart=always）。
  - 文档说明如何起 2 个（默认）到 4 个 worker、如何看日志、如何停。
  - 平台差异只在 deploy/ 配置，业务代码无 `if mac/linux`。
- 风险：路径/Python 解释器因机器而异 → 配置用占位符 + README 说明替换。
- 回滚：删除 deploy/ 配置；worker 仍可手动 CLI 启动。

### A6 — A 阶段回归测试套件（汇总验收）
确保以下场景全绿（部分已存在，A6 负责补齐与统一验证）：
- generate_now 创建任务（`apps/api/tests/test_queue_action_endpoint.py`）
- cancel running/pending task（`test_task_store.py` / `test_task_worker.py`）
- retry failed task（`test_task_store.py`）
- stale running task 被回收（`test_task_store.py` / `test_task_worker.py` A2）
- 两个 worker 并发 claim 不重复（A3）
- 同 queue_id 不重复 active 执行（A3）
- 验收：`python -m pytest core/ apps/api/tests/` 全绿；前端 `npm test` 全绿。

## B 阶段任务列表（仅计划，A 完成后再评估，不在本轮实现）

### B1 — 指数退避 + jitter
- 改动文件：`core/runtime/task_models.py`（新增纯函数 `compute_backoff(attempts, base, cap, jitter)`）；
  `task_store.fail_task` 改用它。
- 测试文件：`core/runtime/tests/test_task_models.py`（新增）。
- 验收：退避随 attempts 指数增长且有上限 cap；jitter 在 [0, jitter] 范围；纯函数可单测无随机依赖（注入 rng）。
- 不与 A 阶段混在同一改动里。

### B2 — 完整 task log 文件
- 每任务 stdout/stderr 写 `data/runtime/logs/tasks/<task_id>.log`，成功失败都留。
- 注意单文件大小上限与轮转；与 B3 清理联动。

### B3 — TTL 清理
- 第一版不删 DB 记录：只清过期日志，或提供 dry-run 预览。
- 若后续清 DB：只允许终态（succeeded/failed/cancelled），**永不碰 pending/running**。

### B4 — 优先级老化
- 后置。当前继续 `priority ASC, created_at ASC`。
- 不在 A 阶段引入有效优先级 SQL，避免改变调度行为引入新 bug。

## 风险与回滚总览

| 任务 | 主要风险 | 回滚方式 |
|------|---------|---------|
| A1 | 旧库迁移失败 | IF NOT EXISTS + try/except；表无读依赖可弃用 |
| A2 | 维护异常拖垮消费 | try/except 吞异常；移除维护调用退回纯消费 |
| A3 | SQLite 写锁竞争 | 起单 worker 退回原行为 |
| A4 | 聚合查询性能 | 数据量小可接受；移除接口即回滚 |
| A5 | 机器路径差异 | README 占位符；删 deploy/ 退回手动启动 |

## 测试策略

- 单元/集成：pytest，沿用现有 `store` fixture（临时文件库，非内存，覆盖并发）。
- 并发：用 `threading` 起多线程并发 claim，断言无重复（沿用 `test_two_claims_do_not_get_same_task` 思路扩展）。
- 前端：vitest，沿用 `taskQueueViews.test.ts` 模式。
- 验收命令：`python -m pytest core/ apps/api/tests/ -q` + `cd apps/web && npm test`。

