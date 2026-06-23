# Code Structure

> 架构为 capability-domain（core 能力域 + pipeline step）。历史 `agents/` 架构说明
> 见 `docs/archive/`，不代表当前架构。

## 项目结构

```
miniapp-factory/
├── pyproject.toml                 ← Python packaging（core + apps 单一依赖清单）
├── apps/
│   ├── api/main.py                ← FastAPI 后端统一入口
│   ├── api/tests/                 ← API 回归测试（auth/real-inputs/path-traversal/ws）
│   └── web/                       ← Vue 3 前端控制台
│
├── core/                          ← 唯一核心业务层（能力域架构）
│   ├── pipeline/runner.py         ← 编排层（只 step 编排，不含业务规则）
│   ├── opportunity/               ← 机会发现 + 评分决策
│   │   ├── scrapers/              ← App Store / Google Play / 小程序 抓取
│   │   ├── demand_analysis.py     ← 需求强度分析
│   │   ├── gap_analysis.py        ← 平台覆盖缺口
│   │   ├── scoring.py             ← Opportunity Score
│   │   ├── viral_score.py         ← Viral Score 传播力评分
│   │   └── classifier.py          ← 题材归类 + 模板选择
│   ├── generator/                 ← 唯一生成真源
│   │   ├── prd_builder.py         ← PRD 生成
│   │   └── src/templates/         ← base + ai-* + *-viral 模板工厂
│   ├── growth/                    ← growth-plan.md / share-strategy.md
│   ├── qa/                        ← engineering / growth / compliance / readiness
│   ├── publisher/                 ← 上架材料 + Telegram 部署
│   ├── platforms/                 ← 平台规则与差异
│   ├── integrations/              ← 外部服务接入（LLM 等）
│   ├── runtime/                   ← config / context / artifacts / database / manifest
│   └── shared/                    ← 跨域 schema / types
│
├── data/
│   ├── samples/apps.json          ← 样例数据
│   ├── inputs/real/               ← 真实导入数据
│   ├── platforms/                 ← 平台库
│   ├── platform-auth/             ← 平台授权配置
│   └── outputs/                   ← 每次运行的产物
│
└── docs/                          ← 文档
```

## 主要入口

| 场景 | 命令 | 说明 |
|------|------|------|
| 一键主流程 | `python -m core.pipeline.auto_runner --regions CN,US --platforms app_store --max-generate 1` | 抓取→队列→生成（正式） |
| 抓取生成队列 | `python core/pipeline/runner.py --mode crawl --regions CN,US --platforms app_store` | 只抓取（正式） |
| 消费队列生成 | `python core/pipeline/runner.py --mode queue` | 默认模式（正式） |
| 运行 pipeline | `python core/pipeline/runner.py --mode demo` | 样例数据 [dev-only，非主流程] |
| 运行 pipeline | `python core/pipeline/runner.py --mode real` | 手动导入 [legacy，非主流程] |
| 启动后端 | `python apps/api/main.py` | FastAPI on :8000 |
| 启动前端 | `cd apps/web && npm run dev` | Vite on :5173 |

## 数据流

```
crawl (App Store / Google Play 多地区, 榜单+搜索)
  → candidate-pool（标准化去重）
  → feature-opportunities（大 App 拆功能）
  → opportunity-queue（生产队列, 正式数据源）
  → queue/auto generation
      → PRD → Codegen → PublishMaterials → Growth → PublishPackage
      → EngineeringQA → GrowthComplianceQA → Readiness
  → data/outputs/{jobId}/
      prd.md / prd.json
      generated/miniapp/ (可 build)
      listing-materials.md / .json
      publish-package/ / submit-status.json
      qa-report.json / pipeline-report.json / template-selection.json / generator-source.json
  → data/opportunity/  (crawl 产物: candidate-pool / feature-opportunities /
      opportunity-queue / crawl-report / processed-apps)
```
