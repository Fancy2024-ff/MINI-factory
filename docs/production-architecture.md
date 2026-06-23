# 生产架构规划 - 7x24 小程序上架工厂

> 当前阶段: 可演示自动化原型
> 目标阶段: 7x24 持续生产系统

## 架构模块

### 数据采集层
- **Scheduler**: 定时扫描 App Store / Google Play 排行榜
- **Data Collector**: 七麦 API、SensorTower API、App Store Connect API
- **Mini Program Search**: 各平台小程序搜索（搜狗微信搜索、支付宝搜索等）

### 能力域 + Pipeline 编排层
> 架构为 capability-domain：`core/pipeline/runner.py` 只做 step 编排，业务正文在各 `core/<域>`。
> 运行时协议主字段为 `step` / `capability`，无 Agent 层。
- **opportunity**: 机会评分 + Viral Score（8 维）+ 题材归类/选模板
- **platforms**: 平台适配推荐（读取 platform-registry.json）+ 平台差异
- **generator**: PRD 生成 + 代码生成（唯一执行真源 `core/generator/codegen.py`）
- **growth**: 增长计划 + 分享/裂变策略
- **qa**: 工程 QA + 增长 QA + 合规 QA + 提交就绪判断
- **publisher**: 上架材料 + 提交包 + 平台 CLI 上传（miniprogram-ci / devvit CLI 等）+ Telegram 部署
- **integrations / runtime / shared**: LLM 接入 / 运行时基础设施 / 跨域 schema

### 基础设施层
- **Worker Queue**: 任务队列（Celery / BullMQ）
- **Database**: Job 状态持久化（PostgreSQL / SQLite）
- **Object Storage**: 产物存储（本地 / S3）
- **Alert**: 失败告警（邮件 / 企微 / Telegram Bot）
- **Auth Vault**: 平台密钥管理（加密存储）

### 展示层
- **Dashboard**: Vue 3 实时看板
- **WebSocket**: 实时流程推送
- **API**: RESTful 控制接口
- **CLI**: 命令行触发入口

## 当前已实现

| 模块 | 状态 | 说明 |
|------|------|------|
| 市场抓取 | ✅ | core/opportunity/crawl_runner：App Store/Google Play 多地区、榜单(top_free/top_grossing)+搜索 |
| 机会队列 | ✅ | candidate-pool → feature-opportunities → opportunity-queue（正式数据源） |
| 数据读取 | ✅ | 正式：data/opportunity/opportunity-queue.json；data/samples(demo)/data/inputs/real(real) 仅 dev-only/legacy |
| 机会评分 | ✅ | 6 维度本地规则（Viral Score 为核心维度，权重 0.25） |
| 传播力评分 | ✅ | Viral Score 8 维度，参与候选选择与机会决策 |
| 模板工厂 | ✅ | 5 类传播型模板（avatar/sticker/pet-talk/funny-video/blessing-video）真实可构建 |
| 平台推荐 | ✅ | 读取 platform-registry.json |
| PRD 生成 | ✅ | 模板化 |
| 代码生成 | ✅ | uni-app 骨架 + 题材模板 overlay |
| 增长产物 | ✅ | growth-plan.md / share-strategy.md |
| 构建验证 | ✅ | npm install + build |
| QA 检查 | ✅ | 三层：工程 QA / 增长 QA / 合规 QA |
| 提交包生成 | ✅ | publish-package/ |
| 实时日志 | ✅ | WebSocket 推送 |
| Dashboard | ✅ | Vue 3 SPA |

## 下一步实现

| 模块 | 优先级 | 依赖 |
|------|--------|------|
| 七麦 API 接入 | P1 | API Key |
| LLM 评分替换 | P1 | Anthropic API Key |
| miniprogram-ci 上传 | P1 | 微信 CI 私钥 |
| Telegram Bot 自动配置 | P1 | Bot Token |
| Discord Activity 部署 | P2 | Application ID |
| 定时扫描调度 | P2 | Scheduler 模块 |
| 审核结果回填 | P2 | Webhook / 轮询 |
| 告警通知 | P2 | 通知渠道配置 |
| 多 Job 并发 | P3 | Worker Queue |
| 生产数据库 | P3 | PostgreSQL |

## 运行模式

| 模式 | 说明 | 数据源 | 频率 |
|------|------|--------|------|
| 试运行 | 检查 pipeline 管线健康 | 本地样例 | 按需 |
| 生产运行 | 真实选品分析 | 导入/API 采集 | 按需 → 定时 |
| 监控模式 | 审核状态跟踪 | 平台 Webhook | 持续 |
