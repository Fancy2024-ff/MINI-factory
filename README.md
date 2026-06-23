# Mini App Factory

能力域（capability domains）驱动的小程序批量生产系统。自动发现 App Store / Google Play 上已验证的 AI 应用需求，评估机会与传播力，识别小程序生态供给缺口，生成产品方案、代码、增长策略与上架材料。

> 架构主心智：系统按**能力域 + pipeline 步骤（step）**组织（opportunity / generator /
> growth / qa / publisher / platforms / integrations / runtime），不是 Agent 架构。
> 运行时主字段为 `step` / `capability`。

## 当前 MVP 已跑通

- 一条命令完成 10+ 步流水线闭环
- 从 5 个候选 App 中自动选择最优机会
- 自动生成 PRD、uni-app 小程序代码、上架材料、人工操作指南
- 自动执行 npm install + npm run build:mp-weixin
- QA 自动验证构建产物（文件完整性、乱码检测、路径校验、构建验证）
- 生成的 dist/build/mp-weixin 可直接导入微信开发者工具
- WebSocket 实时日志推送（per-job 路由 + 指数退避重连）
- API 全链路认证（常量时间比较、路径穿越防御）
- 自动化测试覆盖核心路径（core pytest + dashboard vitest + generator vitest）

## 快速开始

### 主链路（正式）：抓取 → 机会发现 → 生成

正式数据流：

```
crawl market data (App Store / Google Play, 多地区, 榜单+搜索)
  → candidate-pool（标准化去重）
  → feature-opportunities（大 App 拆功能）
  → opportunity-queue（生产队列）
  → queue/auto generation（消费队列生成小程序）
  → QA / growth / publish 产物
```

```bash
# 一键主流程：抓取 → 机会队列 → 生成一个 feature 级小程序
python -m core.pipeline.auto_runner --job-id auto-001 \
    --regions CN,US --platforms app_store --limit 10 --max-generate 1

# 或分步：
python core/pipeline/runner.py --mode crawl --regions CN,US --platforms app_store  # 只抓取生成队列
python core/pipeline/runner.py --mode queue                                        # 消费队列生成（默认模式）
```

正式输入来自 `data/opportunity/opportunity-queue.json`（由 `core.opportunity.crawl_runner` 生成），
不再来自手动导入或样例数据。

### 日常抓取脚本

`scripts/crawl_opportunities.py` 是正式抓取入口（presets + 摘要 + 空队列告警），适合日常/定时任务：

```bash
python scripts/crawl_opportunities.py --preset quick --dry-run   # 小规模测试
python scripts/crawl_opportunities.py --preset cn --limit 20     # 只抓 CN App Store
python scripts/crawl_opportunities.py --preset global --limit 20 # 全地区 App Store + Google Play
# PowerShell 薄包装：
#   .\scripts\crawl_opportunities.ps1 --preset cn --limit 20
```

presets：`cn`(CN App Store) / `global`(10 地区双平台) / `asia`(亚洲) / `quick`(快测) /
`top`(只榜单) / `search`(只搜索)。显式 `--regions/--platforms/--categories/--entry-types/--limit`
覆盖 preset。queue_pending=0 时脚本打印 warning 与可能原因。

> demo / real 模式仅 dev-only / legacy（本地开发、兼容旧 API 测试），非主流程，勿用于正式生产。

执行后生成：
```
data/outputs/{jobId}/
  prd.md / prd.json       - 产品文档
  listing-materials.*     - 上架材料
  human-actions.md        - 人工操作指南
  qa-report.json          - 质量检查报告
  template-selection.json - 选中模板
  generated/miniapp/      - 小程序项目代码
    dist/build/mp-weixin/ - 构建产物（可导入微信开发者工具）
```

### 启动后端 API

```bash
pip install -e ".[dev]"     # 从 repo 根安装（pyproject.toml）
python apps/api/main.py
```

后端运行在 http://localhost:8000

### 启动前端 Dashboard

```bash
cd apps/web
npm install
npm run dev
```

前端运行在 http://localhost:5173

### 用微信开发者工具导入

1. 打开微信开发者工具
2. 选择"导入项目"
3. 目录选择：`data/outputs/{jobId}/generated/miniapp/dist/build/mp-weixin`
4. 填入 AppID（或使用测试号）
5. 即可预览和调试

## 项目结构

```
miniapp-factory/
  pyproject.toml             - Python packaging（core + apps 单一依赖清单）
  apps/
    api/main.py              - FastAPI 后端（认证、WS、Pipeline 管理）
    web/                     - Vue 3 前端（WS 实时推送）
  core/                      - 唯一核心业务层（能力域架构）
    pipeline/runner.py       - 编排层（只 step 编排，不含业务规则）
    opportunity/             - 机会发现 + Opportunity/Viral Score + 题材归类/选模板
      scrapers/              - App Store / Google Play / 小程序 抓取
    generator/               - 唯一生成真源（模板/页面/构建基线）
    growth/                  - 增长策略（growth-plan.md / share-strategy.md）
    qa/                      - engineering / growth / compliance 三类质检
    publisher/               - 上架交付（listing / publish package / Telegram 部署）
    platforms/               - 平台规则与差异
    integrations/            - 外部服务接入（LLM 等）
    runtime/                 - 运行时基础设施（config/context/artifacts/database）
    shared/                  - 跨域共享 schema/types/constants
  data/
    samples/apps.json        - 候选 App 数据
    outputs/                 - 每次运行的产物
```

> 架构落点规则见各 `core/<域>/README.md`。新增功能"一眼能判断"落点：
> 传播/评分→opportunity，模板→generator，增长/分享→growth，质检→qa，
> 平台差异→platforms，外部服务→integrations，运行时→runtime，公共 schema→shared。

## Docker 部署（推荐）

```bash
cp .env.example .env
# 编辑 .env，必须设置：
#   DASHBOARD_API_KEY — API 认证密钥
#   ANTHROPIC_API_KEY — LLM 调用密钥（可选，demo 模式不需要）
docker compose up --build
```

两个服务自动编排：
- API (FastAPI): http://localhost:8000 — 含 Python 生成主链路（core/generator/codegen.py）
- Dashboard (nginx): http://localhost:5173

> Node generator 服务**不在生产编排中**：miniapp 生成的唯一执行真源是 Python
> `core/generator/codegen.py`，由 API 内的 pipeline 直接调用。Node 的
> `core/generator`（page-builder.ts / index.ts）仅作 vitest / Node 生态兼容工具，
> 不需要起服务、不需要 `GENERATOR_API_KEY` / `GENERATOR_URL`。详见 `core/generator/README.md`。

停止：`docker compose down`

已知部署风险：
- `VITE_API_TOKEN` 通过 build-arg 烘焙进前端 JS bundle。内部 MVP 可接受，对外生产应改为 runtime config（nginx 提供 `/config.json`）或后端 session 方案。
- 更换 API key 需要重新 build dashboard 镜像。

## 环境要求（本地开发）

- Python 3.11+
- Node.js 18+
- npm
- Docker（可选，用于容器化部署）

## 运行测试

```bash
# 后端 core（opportunity/growth/runtime/pipeline 等）
pip install -e ".[dev]"
python -m pytest core -q

# 前端 (dashboard)
cd apps/web
npm test -- --run

# Generator
cd core/generator
npm test -- --run
```

## 安全特性

- API Key 认证（POST + 敏感 GET 路由）
- WebSocket token 校验（query param）
- 常量时间比较防 timing attack
- 路径穿越防御
- CORS 限定 origin
- HTTP 安全头（X-Content-Type-Options, X-Frame-Options, Cache-Control）
- 生产环境强制要求密钥配置
- Graceful shutdown（SIGTERM 清理子进程）

## 已知限制（设计取舍，非 Bug）

- **单 worker + 全局状态** — 同时只能运行一个 Pipeline，不支持水平扩展
- **JSON 文件数据库** — MVP 级别，并发写受 filelock 约束
- **核心链路为规则版 v1** — opportunity/viral/growth 评分与策略为可解释规则，LLM 增强走 `core/integrations`，属下一阶段
- **Vue 组件零 render 测试** — 组件无 render/interaction test（数据层有测试）
- **WebSocket token 在 query string** — 浏览器 WS API 限制，已文档化
- **Scraper 使用搜狗/百度作为代理** — 准确率有限，短名称(≤3字符)跳过

## 文档地图

当前权威文档（其余历史文档已归档到 `docs/archive/` 与 `docs/reports/`，顶部均有标识）：

| 主题 | 文档 |
|---|---|
| 项目结构 / 入口 | `docs/CODE_STRUCTURE.md`、`docs/architecture/PROJECT_STRUCTURE.md` |
| 步骤 / 能力图 | `docs/architecture/STEP_CAPABILITY_MAP.md` |
| 运行手册 | `docs/operation/RUNBOOK.md` |
| 各能力域职责与落点 | `core/<域>/README.md` |

## TODO

- [ ] 接入 Claude API 替换本地评分规则
- [ ] LLM 驱动的代码增强（更智能的页面逻辑）
- [ ] 审核结果回填 + 自动复盘迭代
- [ ] miniprogram-ci 自动上传（替代手动上架）
- [ ] 任务队列替换子进程模型（支持并发 Pipeline）
- [ ] SQLite/PostgreSQL 替换 JSON 文件数据库
- [ ] Rate limiting
- [ ] Vue 组件测试 + E2E 测试
