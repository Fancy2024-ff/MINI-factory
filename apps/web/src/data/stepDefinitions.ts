export interface StepDefinition {
  id: string
  step: string
  name: string
  nameEn: string
  phase: string
  purpose: string
  devPurpose: string
  inputs: string[]
  outputs: string[]
  codeLocation: string
  rulesLocation: string
  changeHint: string
  implType: '规则' | '模板' | 'API' | '可选'
  automation: string
  humanRequired: string
}

// 能力域 / pipeline 步骤说明。codeLocation 指向重构后的 core 能力域真源。
export const STEP_DEFINITIONS: StepDefinition[] = [
  {
    id: 'market_input', step: 'MarketInput', name: '市场输入', nameEn: 'MarketInput', phase: '数据',
    purpose: '读取机会队列、样例或手动导入的 App 数据，选出本次生产线要处理的候选 App。',
    devPurpose: '统一 crawl / queue / auto 正式主链路与 dev-only 输入兼容，输出 candidate.json。',
    inputs: ['data/opportunity/opportunity-queue.json', 'data/samples/apps.json [dev-only]', 'data/inputs/real/apps.json [legacy/dev-only]'],
    outputs: ['candidate.json'], codeLocation: 'core/pipeline/runner.py:load_market_input + core/opportunity/crawl_runner.py', rulesLocation: 'core/pipeline/runner.py 输入模式选择逻辑',
    changeHint: '候选 App 选错：优先看 opportunity-queue 的来源、feature 拆解和 load_market_input 转换逻辑。', implType: '规则', automation: '自动消费机会队列并读取输入数据', humanRequired: '生产运行只需准备抓取配置；样例/手动导入仅供开发兼容',
  },
  {
    id: 'demand_analysis', step: 'DemandAnalysis', name: '需求分析', nameEn: 'DemandAnalysis', phase: '分析',
    purpose: '判断这个 App 的用户需求强不强，例如下载量、评分、评论数、付费模式。', devPurpose: '把候选 App 转成 demand_score 和需求理由。',
    inputs: ['candidate.json'], outputs: ['analysis.json'], codeLocation: 'core/opportunity/demand_analysis.py', rulesLocation: 'core/opportunity/demand_analysis.py 评分权重',
    changeHint: '需求评分不准：改 core/opportunity/demand_analysis.py 的评分阈值和权重。', implType: '规则', automation: '自动评分', humanRequired: '需要产品经理校准评分规则',
  },
  {
    id: 'gap_check', step: 'GapCheck', name: '平台缺口', nameEn: 'GapCheck', phase: '分析',
    purpose: '检查微信、Telegram、Discord 等小程序平台有没有类似产品，判断缺口。', devPurpose: '结合平台库和搜索启发式，输出各平台 coverage/gap。',
    inputs: ['candidate.json', 'data/platforms/platform-registry.json'], outputs: ['gap-check.json'], codeLocation: 'core/opportunity/gap_analysis.py', rulesLocation: 'data/platforms/platform-registry.json + core/opportunity/gap_analysis.py',
    changeHint: '平台推荐不对：改 platform-registry.json 或 core/opportunity/gap_analysis.py。', implType: '规则', automation: '自动检查平台覆盖', humanRequired: '需要补真实平台调研/API 证据',
  },
  {
    id: 'opportunity_score', step: 'OpportunityScore', name: '机会评分', nameEn: 'OpportunityScore', phase: '分析',
    purpose: '综合需求强度、平台缺口、小程序适配度、实现难度和风险，算出是否值得做。', devPurpose: '把 analysis.json 和 gap-check.json 合成 opportunity-report.json。',
    inputs: ['analysis.json', 'gap-check.json'], outputs: ['opportunity-report.json'], codeLocation: 'core/opportunity/scoring.py', rulesLocation: 'core/opportunity/scoring.py weights',
    changeHint: '机会分不合理：改 core/opportunity/scoring.py 的 weights 和阈值。', implType: '规则', automation: '自动综合评分', humanRequired: '需要老板/产品确认机会判断口径',
  },
  {
    id: 'viral_score', step: 'ViralScore', name: '传播力评分', nameEn: 'ViralScore', phase: '分析',
    purpose: '判断这个题材有没有传播力（分享动机、社交货币、低门槛、激励回环、情绪强度），并选模板。', devPurpose: '输出 viral-score.json 和 template-selection.json。',
    inputs: ['candidate.json', 'opportunity-report.json'], outputs: ['viral-score.json', 'template-selection.json'], codeLocation: 'core/opportunity/viral_score.py + core/opportunity/classifier.py', rulesLocation: 'core/opportunity/viral_score.py 维度权重 + classifier 题材规则',
    changeHint: '传播力/选模板不对：改 core/opportunity/viral_score.py 或 classifier.py。', implType: '规则', automation: '自动评分 + 题材归类', humanRequired: '需要运营校准传播力口径',
  },
  {
    id: 'prd_generation', step: 'PRD', name: '生成 PRD', nameEn: 'PRD', phase: '生成',
    purpose: '把机会判断转成产品需求文档，说明要做什么小程序、核心功能是什么。', devPurpose: '生成 prd.md 和 prd.json，供代码生成使用。',
    inputs: ['candidate.json', 'opportunity-report.json'], outputs: ['prd.md', 'prd.json'], codeLocation: 'core/generator/prd_builder.py', rulesLocation: 'core/generator/prd_builder.py PRD 模板',
    changeHint: 'PRD 不像产品文档：改 core/generator/prd_builder.py 的模板和字段。', implType: '模板', automation: '自动生成 PRD', humanRequired: '复杂产品需要人工复核需求边界',
  },
  {
    id: 'code_generation', step: 'Codegen', name: '生成代码', nameEn: 'Codegen', phase: '生成',
    purpose: '根据 PRD、题材模板生成 uni-app 小程序项目。', devPurpose: '复制 base + 题材 overlay、token 注入、写文档。',
    inputs: ['prd.json', 'template-selection.json', 'core/generator/src/templates/'], outputs: ['generated/miniapp/', 'generator-source.json'], codeLocation: 'core/generator/codegen.py（唯一执行真源）', rulesLocation: 'core/generator/src/templates/',
    changeHint: '小程序页面不对：改 core/generator/src/templates 或 core/generator/codegen.py。', implType: '模板', automation: '自动生成项目代码', humanRequired: '复杂页面仍需要开发补充模板能力',
  },
  {
    id: 'publish_materials', step: 'PublishMaterials', name: '上架材料', nameEn: 'PublishMaterials', phase: '上架',
    purpose: '生成应用名称、简介、关键词、审核备注、隐私摘要等上架材料。', devPurpose: '生成 listing-materials.md/json。',
    inputs: ['candidate.json', 'prd.json'], outputs: ['listing-materials.md', 'listing-materials.json'], codeLocation: 'core/publisher/materials.py', rulesLocation: 'core/publisher/materials.py 上架材料模板',
    changeHint: '上架文案不合适：改 core/publisher/materials.py 的模板。', implType: '模板', automation: '自动生成材料', humanRequired: '提交前需要人工确认敏感词和资质材料',
  },
  {
    id: 'growth_strategy', step: 'Growth', name: '增长策略', nameEn: 'Growth', phase: '增长',
    purpose: '生成增长计划和分享策略：冷启动、渠道、裂变回环、分享钩子、激励、去水印建议。', devPurpose: '生成 growth-plan.md 和 share-strategy.md。',
    inputs: ['viral-score.json', 'template-selection.json'], outputs: ['growth-plan.md', 'share-strategy.md'], codeLocation: 'core/growth/planner.py + core/growth/share_strategy.py', rulesLocation: 'core/growth/',
    changeHint: '增长/分享策略不合适：改 core/growth/planner.py 或 share_strategy.py。', implType: '模板', automation: '自动生成增长/分享策略', humanRequired: '运营需要按真实渠道细化',
  },
  {
    id: 'submit_package', step: 'PublishPackage', name: '提交审核包', nameEn: 'PublishPackage', phase: '上架',
    purpose: '按平台生成提交目录、材料清单和审核说明。', devPurpose: '根据平台库输出 publish-package/ 和 submit-status.json。',
    inputs: ['listing-materials.json', 'data/platforms/platform-registry.json'], outputs: ['publish-package/', 'submit-status.json'], codeLocation: 'core/publisher/package_builder.py + core/platforms/guides.py', rulesLocation: 'core/platforms/guides.py + data/platforms/platform-registry.json',
    changeHint: '平台材料缺失：改 core/platforms/guides.py 或平台注册表。', implType: '规则', automation: '自动整理提交包', humanRequired: '平台账号、主体资质、密钥配置仍需人工一次性准备',
  },
  {
    id: 'build_qa', step: 'EngineeringQA', name: '构建质检', nameEn: 'EngineeringQA', phase: 'QA',
    purpose: '安装依赖、构建小程序、检查乱码、路径、文件完整性和 dist 产物。', devPurpose: '执行 npm install + npm run build:mp-weixin 并生成 qa-report.json。',
    inputs: ['generated/miniapp/'], outputs: ['qa-report.json', 'dist/build/mp-weixin/'], codeLocation: 'core/qa/engineering_qa.py', rulesLocation: 'core/qa/engineering_qa.py QA checks',
    changeHint: '构建失败：看 qa-report.json issues，再改模板或依赖版本。', implType: 'API', automation: '自动构建和检查', humanRequired: '构建环境和 npm 源需要稳定',
  },
  {
    id: 'growth_compliance_qa', step: 'GrowthComplianceQA', name: '增长/合规质检', nameEn: 'GrowthComplianceQA', phase: 'QA',
    purpose: '检查增长产物是否齐全（含分享/裂变要素）以及合规材料（隐私、协议、审核备注）。', devPurpose: '生成 growth-qa-report.json 和 compliance-qa-report.json。',
    inputs: ['growth-plan.md', 'share-strategy.md', 'docs/privacy-policy.md'], outputs: ['growth-qa-report.json', 'compliance-qa-report.json'], codeLocation: 'core/qa/growth_qa.py + core/qa/compliance_qa.py', rulesLocation: 'core/qa/',
    changeHint: '增长/合规质检规则调整：改 core/qa/growth_qa.py 或 compliance_qa.py。', implType: '规则', automation: '自动质检', humanRequired: '合规需要法务最终确认',
  },
  {
    id: 'readiness', step: 'Readiness', name: '提交就绪', nameEn: 'Readiness', phase: '上架',
    purpose: '判断当前产物是否真的可以提交审核，以及阻塞项是什么。', devPurpose: '生成 submission-readiness-report.json。',
    inputs: ['qa-report.json', 'submit-status.json', 'publish-package/'], outputs: ['submission-readiness-report.json'], codeLocation: 'core/qa/readiness.py', rulesLocation: 'core/qa/readiness.py blocking/warning 规则',
    changeHint: '可提交判断不对：改 core/qa/readiness.py 的规则。', implType: '规则', automation: '自动判断提交状态', humanRequired: '缺平台授权时必须人工补配置',
  },
  {
    id: 'telegram_deploy', step: 'TelegramDeploy', name: 'Telegram 部署', nameEn: 'TelegramDeploy', phase: '发布',
    purpose: '可选步骤：把 H5 WebApp 部署到 Cloudflare Pages 并配置 Telegram Bot 菜单。', devPurpose: '调用 core/publisher/telegram_deploy.py。',
    inputs: ['job output', 'TELEGRAM_BOT_TOKEN', 'CLOUDFLARE_API_TOKEN'], outputs: ['telegram-deploy.json'], codeLocation: 'core/publisher/telegram_deploy.py', rulesLocation: 'core/publisher/templates/telegram-webapp/',
    changeHint: 'Telegram 自动部署失败：看 token、Cloudflare 配置和 telegram-deploy.json。', implType: '可选', automation: '配置齐全后可自动部署', humanRequired: '需要 Telegram Bot 和 Cloudflare 授权',
  },
]

export const PHASES = ['全部', '数据', '分析', '生成', '增长', 'QA', '上架', '发布']

export function findStepDefinition(stepId?: string | null) {
  if (!stepId) return null
  return STEP_DEFINITIONS.find(item => item.id === stepId || item.step === stepId) || null
}
