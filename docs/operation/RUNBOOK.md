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
