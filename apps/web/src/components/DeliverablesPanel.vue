<script setup lang="ts">
import { computed } from 'vue'
import type { JobDetail } from '../types/job'

const props = defineProps<{
  job: JobDetail | null
}>()

interface DeliverableItem {
  key: string
  name: string
  purpose: string
}

const PRODUCT_DELIVERABLES: DeliverableItem[] = [
  { key: 'candidate.json', name: '候选应用', purpose: '筛选出的目标应用信息' },
  { key: 'analysis.json', name: '需求分析', purpose: '需求强度评分和市场验证' },
  { key: 'gap-check.json', name: '平台缺口', purpose: '小程序平台覆盖情况' },
  { key: 'opportunity-report.json', name: '机会评估', purpose: '综合机会评分和推荐' },
  { key: 'viral-score.json', name: '传播力评分', purpose: 'Viral Score 与传播维度' },
  { key: 'template-selection.json', name: '模板选择', purpose: '传播题材归类与生成模板' },
  { key: 'prd.json', name: '产品需求文档', purpose: '小程序 PRD 规格书' },
  { key: 'prd.md', name: 'PRD 可读版', purpose: '产品需求文档 Markdown 版' },
]

const ENGINEERING_DELIVERABLES: DeliverableItem[] = [
  { key: 'miniapp', name: '小程序源码', purpose: '生成的完整小程序代码' },
  { key: 'dist', name: '构建产物', purpose: '编译后的可部署包' },
  { key: 'qa-report.json', name: 'QA 报告', purpose: '质量检查和合规验证结果' },
  { key: 'pipeline-report.json', name: '流水线报告', purpose: '完整的执行步骤和状态' },
  { key: 'generator-source.json', name: '代码来源', purpose: '代码生成模板来源记录' },
]

const LISTING_DELIVERABLES: DeliverableItem[] = [
  { key: 'listing-materials.md', name: '上架材料', purpose: '平台提交所需的描述和文案' },
  { key: 'listing-materials.json', name: '上架材料(结构化)', purpose: '结构化上架数据' },
  { key: 'publish-package', name: '发布包', purpose: '多平台提交目录' },
  { key: 'human-actions.md', name: '人工操作清单', purpose: '需要人工完成的步骤' },
  { key: 'submission-readiness-report.json', name: '提交就绪度', purpose: '是否满足提交条件' },
  { key: 'submit-status.json', name: '提交状态', purpose: '各平台提交流转状态' },
]

const GROWTH_DELIVERABLES: DeliverableItem[] = [
  { key: 'growth-plan.md', name: '增长计划', purpose: '冷启动、渠道、裂变回路与指标' },
  { key: 'share-strategy.md', name: '分享策略', purpose: '分享钩子、激励与去水印设计' },
  { key: 'growth-qa-report.json', name: '增长 QA', purpose: '增长交付物完整性检查' },
  { key: 'compliance-qa-report.json', name: '合规 QA', purpose: '隐私、协议与审核备注检查' },
  { key: 'generator-qa-report.json', name: '生成器 QA', purpose: '模板配置 / 蓝图 / 生成产物质量检查' },
]

function hasArtifact(key: string): boolean {
  if (!props.job?.artifacts) return false
  if (key === 'miniapp') return !!props.job.miniapp_path
  if (key === 'dist') return !!(props.job.artifacts?.['qa-report.json']?.checks?.dist_exists)
  if (key === 'publish-package') return !!props.job.artifacts?.['submit-status.json']
  return !!props.job.artifacts[key]
}

function getArtifactPreview(key: string): string {
  if (!props.job?.artifacts) return ''
  const data = props.job.artifacts[key]
  if (!data) return ''
  if (typeof data === 'string') return data.slice(0, 80)
  if (data.name_cn) return data.name_cn
  if (data.name) return data.name
  if (data.viral_score !== undefined) return `Viral: ${data.viral_score} (${data.tier || 'unknown'})`
  if (data.selected_template) return `模板: ${data.selected_template}`
  if (data.preview_type) return `预览: ${data.preview_type}${data.template ? ' / ' + data.template : ''}`
  if (data.score !== undefined) return `评分: ${data.score}`
  if (data.qa_passed !== undefined) return data.qa_passed ? 'QA 通过' : 'QA 未通过'
  if (data.passed !== undefined) return data.passed ? 'QA 通过' : 'QA 未通过'
  return ''
}

function copyArtifact(key: string) {
  if (!props.job?.artifacts) return
  const data = props.job.artifacts[key]
  if (!data) return
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  navigator.clipboard.writeText(text)
}

// 传播闭环产品化分层（P0-2）：区分「产品层已接入 / 只有文档 / 缺失」。
// 数据源：growth-qa-report.json.checks（三层接入检查）+ generator-source.json（事实源摘要）。
const growthQaChecks = computed<Record<string, any>>(() => {
  return props.job?.artifacts?.['growth-qa-report.json']?.checks || {}
})
const growthLoopSummary = computed<Record<string, any>>(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.growth_loop_summary || gs?.codegen_report || {}
})

const propagationStatus = computed(() => {
  const c = growthQaChecks.value
  const hasReport = Object.keys(c).length > 0
  const hasSummary = !!growthLoopSummary.value?.growth_loop_present

  // 完全没有任何传播闭环信号：缺失。
  if (!hasReport && !hasSummary) {
    return { level: 'missing', label: '缺失', detail: '未发现传播闭环数据' }
  }

  // 没有 growth-qa-report：只能凭 generator-source 摘要说「有摘要 / 待 QA 验证」，
  // 不能直接判定「产品层已接入」（finding #3：行为级接入必须由 QA 校验背书）。
  if (!hasReport) {
    return { level: 'partial', label: '仅有摘要 · 待 QA 验证', detail: '有 growth_loop 摘要，待 Growth QA 校验产品层接入' }
  }

  // ready 必须同时满足三层接入 + 7 项 result_displays_* + 能力可见（finding #3）。
  const READY_CHECKS = [
    'growth_loop_in_blueprint',
    'generation_consumes_growth_loop',
    'result_displays_growth_loop',
    'result_displays_share_cta',
    'result_displays_unlock',
    'result_displays_watermark',
    'result_displays_remove_watermark',
    'result_displays_brand',
    'result_displays_export',
    'capability_mode_visible',
  ]
  // 视频边界型 / 核心模板的诚实度守护项：存在即必须为 true 才能 ready。
  const CONDITIONAL_CHECKS = [
    'fallback_preview_visible_for_video_templates',
    'video_template_not_faked_real',
    'core_template_not_downgraded',
  ]

  const coreReady = READY_CHECKS.every((k) => c[k] === true)
  const conditionalReady = CONDITIONAL_CHECKS.every((k) => !(k in c) || c[k] === true)
  const inBlueprint = c.growth_loop_in_blueprint === true

  if (coreReady && conditionalReady) {
    return { level: 'ready', label: '产品层已接入', detail: 'blueprint → generation.ts → result.vue 三层贯通，状态全部可见' }
  }
  if (inBlueprint) {
    return { level: 'partial', label: '设计存在 · 产品层未完全接入', detail: '有传播设计，但结果页/服务未完全消费或状态缺失' }
  }
  return { level: 'doc-only', label: '只有文档', detail: '仅有增长文档，未进入产品层' }
})

interface GlStat { key: string; label: string; ok: boolean | undefined }
const propagationStats = computed<GlStat[]>(() => {
  const c = growthQaChecks.value
  const s = growthLoopSummary.value
  return [
    { key: 'share', label: '分享 CTA', ok: c.result_displays_share_cta ?? s.has_share_cta },
    { key: 'unlock', label: '解锁', ok: c.result_displays_unlock ?? s.has_unlock },
    { key: 'watermark', label: '水印', ok: c.result_displays_watermark ?? s.has_watermark },
    { key: 'remove', label: '去水印', ok: c.result_displays_remove_watermark ?? s.remove_watermark_supported },
    { key: 'brand', label: '品牌露出', ok: c.result_displays_brand ?? s.brand_exposure },
    { key: 'export', label: '导出', ok: c.result_displays_export ?? s.export_supported },
    { key: 'capability', label: '能力模式', ok: c.capability_mode_visible ?? !!s.capability_mode },
  ]
})
</script>

<template>
  <div class="deliverables">
    <!-- Section 1: Product -->
    <section class="section">
      <h3 class="section-heading">产品交付物</h3>
      <div class="items-grid">
        <div v-for="item in PRODUCT_DELIVERABLES" :key="item.key" class="item-card">
          <div class="item-header">
            <span class="item-name">{{ item.name }}</span>
            <span class="item-badge" :class="hasArtifact(item.key) ? 'badge--ready' : 'badge--missing'">
              {{ hasArtifact(item.key) ? '就绪' : '缺失' }}
            </span>
          </div>
          <p class="item-purpose">{{ item.purpose }}</p>
          <p v-if="hasArtifact(item.key)" class="item-preview">{{ getArtifactPreview(item.key) }}</p>
          <div class="item-actions" v-if="hasArtifact(item.key)">
            <button class="action-btn" @click="copyArtifact(item.key)">复制</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 2: Engineering -->
    <section class="section">
      <h3 class="section-heading">工程交付物</h3>
      <div class="items-grid">
        <div v-for="item in ENGINEERING_DELIVERABLES" :key="item.key" class="item-card">
          <div class="item-header">
            <span class="item-name">{{ item.name }}</span>
            <span class="item-badge" :class="hasArtifact(item.key) ? 'badge--ready' : 'badge--missing'">
              {{ hasArtifact(item.key) ? '就绪' : '缺失' }}
            </span>
          </div>
          <p class="item-purpose">{{ item.purpose }}</p>
          <p v-if="hasArtifact(item.key)" class="item-preview">{{ getArtifactPreview(item.key) }}</p>
          <div class="item-actions" v-if="hasArtifact(item.key)">
            <button class="action-btn" @click="copyArtifact(item.key)">复制</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 3: Growth -->
    <section class="section">
      <h3 class="section-heading">增长交付物</h3>

      <!-- 传播闭环产品化状态（P0-2）：产品层已接入 / 只有文档 / 缺失 -->
      <div class="propagation-card" data-testid="propagation-status" v-if="job">
        <div class="prop-header">
          <span class="prop-name">传播闭环（Growth Loop）</span>
          <span class="prop-badge" :class="'prop-badge--' + propagationStatus.level">{{ propagationStatus.label }}</span>
        </div>
        <p class="prop-detail">{{ propagationStatus.detail }}</p>
        <div class="prop-stats">
          <span
            v-for="st in propagationStats"
            :key="st.key"
            class="prop-stat"
            :class="st.ok ? 'prop-stat--ok' : 'prop-stat--no'"
          >{{ st.label }}：{{ st.ok ? '有' : '缺' }}</span>
        </div>
      </div>

      <div class="items-grid">
        <div v-for="item in GROWTH_DELIVERABLES" :key="item.key" class="item-card">
          <div class="item-header">
            <span class="item-name">{{ item.name }}</span>
            <span class="item-badge" :class="hasArtifact(item.key) ? 'badge--ready' : 'badge--missing'">
              {{ hasArtifact(item.key) ? '就绪' : '缺失' }}
            </span>
          </div>
          <p class="item-purpose">{{ item.purpose }}</p>
          <p v-if="hasArtifact(item.key)" class="item-preview">{{ getArtifactPreview(item.key) }}</p>
          <div class="item-actions" v-if="hasArtifact(item.key)">
            <button class="action-btn" @click="copyArtifact(item.key)">复制</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 4: Listing -->
    <section class="section">
      <h3 class="section-heading">上架交付物</h3>
      <div class="items-grid">
        <div v-for="item in LISTING_DELIVERABLES" :key="item.key" class="item-card">
          <div class="item-header">
            <span class="item-name">{{ item.name }}</span>
            <span class="item-badge" :class="hasArtifact(item.key) ? 'badge--ready' : 'badge--missing'">
              {{ hasArtifact(item.key) ? '就绪' : '缺失' }}
            </span>
          </div>
          <p class="item-purpose">{{ item.purpose }}</p>
          <p v-if="hasArtifact(item.key)" class="item-preview">{{ getArtifactPreview(item.key) }}</p>
          <div class="item-actions" v-if="hasArtifact(item.key)">
            <button class="action-btn" @click="copyArtifact(item.key)">复制</button>
          </div>
        </div>
      </div>
    </section>

    <div v-if="!job" class="empty-state">
      <p>暂无任务数据，请先运行流水线</p>
    </div>
  </div>
</template>

<style scoped>
.deliverables {
  animation: fadeIn 0.3s var(--ease-apple);
}

.section {
  margin-bottom: 28px;
}

.section-heading {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-1);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-border);
}

/* Propagation loop productization status */
.propagation-card {
  background: var(--color-surface-solid);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 14px 16px;
  margin-bottom: 14px;
}
.prop-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.prop-name { font-size: 14px; font-weight: 600; color: var(--color-text-1); }
.prop-badge { font-size: 11px; font-weight: 500; padding: 2px 10px; border-radius: 980px; }
.prop-badge--ready { background: var(--color-green-subtle); color: #166534; }
.prop-badge--partial { background: var(--color-orange-subtle); color: #92400e; }
.prop-badge--doc-only { background: var(--color-orange-subtle); color: #92400e; }
.prop-badge--missing { background: rgba(255, 59, 48, 0.08); color: #991b1b; }
.prop-detail { font-size: 12px; color: var(--color-text-2); margin-bottom: 10px; }
.prop-stats { display: flex; flex-wrap: wrap; gap: 6px; }
.prop-stat { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
.prop-stat--ok { background: var(--color-green-subtle); color: #166534; }
.prop-stat--no { background: rgba(0, 0, 0, 0.04); color: var(--color-text-3); }

.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.item-card {
  background: var(--color-surface-solid);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 16px;
  transition: box-shadow 0.2s;
}
.item-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.item-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-1);
}

.item-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 980px;
}
.badge--ready {
  background: var(--color-green-subtle);
  color: #166534;
}
.badge--missing {
  background: rgba(0, 0, 0, 0.04);
  color: var(--color-text-3);
}

.item-purpose {
  font-size: 12px;
  color: var(--color-text-2);
  margin-bottom: 6px;
}

.item-preview {
  font-size: 11px;
  color: var(--color-text-3);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 8px;
}

.item-actions {
  display: flex;
  gap: 6px;
}

.action-btn {
  font-size: 11px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-2);
  cursor: pointer;
  transition: background 0.12s;
}
.action-btn:hover {
  background: rgba(0, 0, 0, 0.03);
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--color-text-3);
  font-size: 14px;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>

