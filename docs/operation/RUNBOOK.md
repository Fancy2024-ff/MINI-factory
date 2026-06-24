# 运行手册

## 本地启动

后端：

```bash
cd apps/api
python main.py
```

前端：

```bash
cd apps/web
npm install
npm run dev
```

运行正式主流程（抓取 → 机会队列 → 生成）：

```bash
# 一键
python -m core.pipeline.auto_runner --regions CN,US --platforms app_store --limit 10 --max-generate 1
# 或分步
python core/pipeline/runner.py --mode crawl --regions CN,US --platforms app_store
python core/pipeline/runner.py --mode queue
```

> 说明：后端统一入口为 `apps/api/main.py`，流水线统一入口为
> `core/pipeline/runner.py`，一键编排为 `core/pipeline/auto_runner.py`。抓取实现统一在
> `core/opportunity/crawl_runner.py`。

### 日常抓取脚本（正式）

`scripts/crawl_opportunities.py`：presets + 摘要 + 空队列告警，供日常抓取/排查/定时任务。

```bash
python scripts/crawl_opportunities.py --preset quick --dry-run
python scripts/crawl_opportunities.py --preset cn --limit 20
python scripts/crawl_opportunities.py --preset global --limit 20
# PowerShell:  .\scripts\crawl_opportunities.ps1 --preset cn --limit 20
```

presets：cn / global / asia / quick / top / search。`--regions/--platforms/--categories/`
`--entry-types/--limit/--max-tasks` 可覆盖 preset。`--dry-run` 不写盘。
queue_pending=0 时打印 warning（rating filter / 关键词未命中 / 已 processed / 数据源无结果）。

## 生产运行输入

正式数据源（canonical）：`data/opportunity/opportunity-queue.json`
（由 `core/opportunity/crawl_runner.py` 抓取生成；不来自手动导入或样例）。

> dev-only / legacy：`--mode demo`（样例 `data/samples/apps.json`）与
> `--mode real`（手动导入 `data/inputs/real/apps.json`）仅供本地开发与兼容旧 API 测试，
> 不是正式主流程。

## 产物位置

每次运行产物都在：`data/outputs/{jobId}/`

根目录不再放运行产物。

## 任务系统（正式执行框架）

**正式主路径 = task queue + task_worker。** API 默认只“创建任务 + 返回 task_id/job_id”，
不在请求线程内直接跑 pipeline。worker 是唯一正式执行者。持久化用标准库 `sqlite3`，
不引入 Celery / Redis / PostgreSQL。

- SQLite DB 默认路径：`data/runtime/tasks.sqlite3`（已在 `.gitignore`，不入库）。
- 任务种类（kind）：`pipeline.run`（默认 `payload.mode=queue`，也支持 crawl/auto/demo/real）、
  `opportunity.crawl`、`pipeline.auto`。
- task ↔ queue item ↔ job 三者映射：task 表有 `queue_id` / `job_id` 一等列；queue item
  记录持有它的 `task_id` / `job_id`；可按 `queue_id` / `job_id` 反查任务。

### 执行模型（默认 async）

- `POST /api/pipeline/start`：**默认 `execution_mode=async`**——按 `mode` 映射成 task 入队
  （queue/demo/real→`pipeline.run`，crawl→`opportunity.crawl`，auto→`pipeline.auto`），
  返回 `task_id` / `job_id`，由 worker 执行。`execution_mode=sync` 走旧的请求线程内
  子进程模型，**仅兼容/调试，非主路径**。
- `POST /api/pipeline/enqueue`：以 `kind` + `payload` 直接表达任务入队。与 start 共享
  同一个 `enqueue` 落库实现（`task_store.enqueue_task`），不存在两套分叉。
- `generate_now`（`POST /api/opportunities/queue/action`）：**正式走 task queue**——提权目标
  queue item + 入队定向 `pipeline.run`（payload 带 `queue_id`），worker 用 `--queue-id`
  只消费该 item。同一 queue item 已有活跃任务（pending/running）时不重复创建，返回 `reused`。

### API（均需 `X-API-Key`）

```bash
# 启动（默认 async 入队）
POST /api/pipeline/start    { "mode": "queue" }            # -> {task_id, job_id, kind, status}
POST /api/pipeline/start    { "mode": "queue", "execution_mode": "sync" }   # 兼容旧子进程模型

# 直接入队
POST /api/pipeline/enqueue  { "kind": "pipeline.run", "payload": {"mode": "queue", "queue_id": "..."} }

# 队列动作（generate_now 走 task queue）
POST /api/opportunities/queue/action  { "action": "generate_now", "queue_id": "..." }

# 查看任务
GET  /api/tasks/summary                 # 按状态/种类聚合统计
GET  /api/tasks                         # 列表，可 ?status= / ?kind= / ?queue_id= / ?job_id= 过滤
GET  /api/tasks/{task_id}               # 单个任务详情
GET  /api/tasks/by-queue/{queue_id}     # 按 queue item 反查任务
GET  /api/tasks/by-job/{job_id}         # 按 job 反查任务

# 管理
POST /api/tasks/{task_id}/cancel             # 取消（pending/running/failed -> cancelled）
POST /api/tasks/{task_id}/retry              # 重试 failed 任务（-> pending，重置 attempts）
POST /api/tasks/maintenance/requeue-stale    # 回收锁过期任务，返回 {requeued, failed}
```

### 启动 worker

```bash
# 常驻 worker（轮询消费，Ctrl-C 优雅停止：跑完当前任务再退出）
python -m core.pipeline.task_worker --worker-id worker-local

# 单次消费一个任务后退出
python -m core.pipeline.task_worker --once

# 最多处理 N 个任务后退出
python -m core.pipeline.task_worker --worker-id worker-local --max-tasks 3

# 回收锁过期（stale）的 running 任务
python -m core.pipeline.task_worker --maintenance requeue-stale

# 查看队列统计 / 演练入队
python -m core.runtime.task_store --summary
python -m core.runtime.task_store --enqueue-test
```

worker 执行任务期间会开后台心跳线程续租锁（间隔 `lock_seconds/3`，夹在 5–60s），
长任务不会被 `requeue-stale` 误回收；取消正在运行的任务时，worker 会感知并
terminate 子进程，不会把它误标成功。

### 定向 queue 消费

`core/pipeline/runner.py --mode queue` 有两种消费：

```bash
python core/pipeline/runner.py --mode queue                  # 普通：消费下一个 pending item
python core/pipeline/runner.py --mode queue --queue-id Q-123  # 定向：只消费指定 queue_id
```

worker 的 `pipeline.run` 在 payload 带 `queue_id` 时自动传 `--queue-id`，保证“点了 A item
就只跑 A item”，绝不串到别的 item。

### 现状与边界

- 当前是**单机 SQLite 任务队列**，不是多机分布式系统（无跨机协调 / 无中心 broker）。
- **不包含微信上架闭环**，也不涉及 miniprogram-ci / 平台提审。
- 同步执行（`execution_mode=sync`）仅作兼容/调试保留，不是主路径。
- 后续项：PostgreSQL、分布式 worker、前端完整任务看板。
