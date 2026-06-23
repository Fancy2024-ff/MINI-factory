# 项目结构说明

本项目分为清晰的四层：`apps` 放可运行应用，`core` 放核心业务能力（按能力域划分），`data` 放输入输出数据，`infra` 放部署配置。

```text
miniapp-factory/
├── apps/
│   ├── web/                 # 前端控制台
│   └── api/                 # 后端统一入口（FastAPI），api/tests/ 回归测试
├── core/
│   ├── pipeline/            # 流水线编排层（只 step 编排）
│   ├── opportunity/         # 机会发现 + 评分（demand/gap/scoring/viral_score/classifier）+ scrapers
│   ├── generator/           # 唯一生成真源（prd_builder + src/templates 模板工厂）
│   ├── growth/              # 增长/分享策略（growth-plan / share-strategy）
│   ├── qa/                  # engineering / growth / compliance / readiness 质检
│   ├── publisher/           # 上架材料 + 平台部署
│   ├── platforms/           # 平台规则与差异
│   ├── integrations/        # 外部服务接入（LLM 等）
│   ├── runtime/             # config / context / artifacts / database / manifest
│   └── shared/              # 跨域公共 schema / types
├── data/
│   ├── opportunity/         # 正式：抓取产物 + opportunity-queue（主数据源）
│   ├── inputs/              # 手动导入 [legacy/dev-only]
│   ├── samples/             # 样例数据 [dev-only]
│   ├── outputs/             # 每次 job 产物
│   ├── platforms/           # 平台库
│   └── platform-auth/       # 平台授权配置模板/本地密钥
├── docs/
├── infra/docker/            # Dockerfile
└── pyproject.toml           # Python packaging（core + apps）
```

## 入口

| 类型 | 入口 |
|---|---|
| 前端 | `apps/web` |
| 后端 API | `apps/api/main.py` |
| Pipeline | `core/pipeline/runner.py` |
| Generator | `core/generator` |
| Telegram 发布 | `core/publisher/telegram_deploy.py` |

## 设计原则

- 后端 API 独立为 `apps/api`，与 `core` 业务能力分离，API 服务不与业务正文混在一起。
- `core` 按**能力域**划分，新增功能"一眼判断落点"（见各 `core/<域>/README.md`）。
- `core/pipeline/runner.py` 只做编排：step 顺序、输入输出传递、产物调度、报告；
  评分/缺口/PRD/上架材料/就绪决策/清单等业务正文均在对应 core 域。
- 架构为 capability-domain（能力域 + pipeline step），没有 Agent 架构层。
  历史 Agent 分工说明见 `docs/archive/`，不代表当前架构。
