<script setup lang="ts">
import { computed } from 'vue'
import type { JobDetail, PipelineStep } from '../types/job'
import StepTimeline from './StepTimeline.vue'
import StepDetailPanel from './StepDetailPanel.vue'
import TerminalDrawer from './TerminalDrawer.vue'
import { ref } from 'vue'

const props = defineProps<{
  job: JobDetail | null
  running: boolean
  logs: string[]
  runtimePipelineSteps: PipelineStep[]
  selectedStepId: string
}>()

const emit = defineEmits<{
  'select-step': [stepId: string]
}>()

const drawerOpen = ref(true)

const pipelineReport = computed(() => {
  return props.job?.artifacts?.['pipeline-report.json']
})

const steps = computed<PipelineStep[]>(() => {
  if (props.running && props.runtimePipelineSteps.length > 0) {
    return props.runtimePipelineSteps
  }
  if (pipelineReport.value?.steps) {
    return pipelineReport.value.steps
  }
  return []
})

const currentStep = computed(() => {
  return steps.value.find(s => s.status === 'running')
})

const completedCount = computed(() => {
  return steps.value.filter(s => s.status === 'passed' || s.status === 'done').length
})

const totalCount = computed(() => {
  // 动态取自 pipeline-report.json / 实时事件的 steps 数量；无数据时为 0，不写死步数。
  return steps.value.length
})

const selectedStep = computed(() => {
  // Priority: explicit selection → failed → running → last step
  if (props.selectedStepId) {
    const found = steps.value.find(s => (s.step || s.capability) === props.selectedStepId)
    if (found) return found
  }
  const failed = steps.value.find(s => s.status === 'failed')
  if (failed) return failed
  const running = steps.value.find(s => s.status === 'running')
  if (running) return running
  if (steps.value.length > 0) return steps.value[steps.value.length - 1]
  return null
})

const appName = computed(() => {
  const c = props.job?.artifacts?.['candidate.json']
  return c?.name_cn || c?.name || ''
})

const jobMode = computed(() => {
  return pipelineReport.value?.mode || ''
})

const viralSummary = computed(() => {
  const viral = props.job?.artifacts?.['viral-score.json']
  if (!viral) return ''
  return `${viral.viral_score ?? '--'} / ${viral.tier || 'unknown'}`
})

const templateSummary = computed(() => {
  const selection = props.job?.artifacts?.['template-selection.json']
  return selection?.selected_template || ''
})

// 预览类型 + 蓝图是否生成（来自 generator-source.json）
const previewTypeSummary = computed(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.preview_type || ''
})

const blueprintSummary = computed(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  if (!gs) return ''
  // generator-source.json 含 preview_type 即表示已走 blueprint 接入流程
  if (gs.preview_type) {
    return gs.blueprint_is_fallback ? 'blueprint 已生成（兜底）' : 'blueprint 已生成'
  }
  return ''
})

// 模板能力真实状态（来自 generator-source.json，P0-1 收口口径）。
const templateStatusSummary = computed(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  if (!gs?.template_status) return ''
  return gs.template_status === 'core_runnable' ? '核心可跑通' : '诚实预览'
})

const generationBackendSummary = computed(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.generation_backend || ''
})

const realGenerationSummary = computed(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  if (!gs || gs.template_status === undefined) return ''
  if (gs.real_generation) return '真实生成'
  return gs.fallback_mode ? 'honest fallback / preview' : '本地预览'
})

const boundaryNoteSummary = computed(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.boundary_note || ''
})

// 传播闭环摘要（来自 generator-source.json.growth_loop_summary / codegen_report，P0-2）。
// 让老板在控制台一眼看出：生成的小程序带不带分享/解锁/水印/去水印/品牌/导出等传播机制。
const growthLoop = computed<Record<string, any>>(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.growth_loop_summary || gs?.codegen_report || {}
})

const growthLoopPresent = computed(() => !!growthLoop.value?.growth_loop_present)

const shareCtaSummary = computed(() => {
  if (!growthLoopPresent.value) return ''
  return growthLoop.value.has_share_cta ? '有' : '无'
})
const unlockSummary = computed(() => {
  if (!growthLoopPresent.value) return ''
  return growthLoop.value.has_unlock ? '有' : '无'
})
const watermarkSummary = computed(() => {
  if (!growthLoopPresent.value) return ''
  return growthLoop.value.has_watermark ? '有' : '无'
})
const removeWatermarkSummary = computed(() => {
  if (!growthLoopPresent.value) return ''
  return growthLoop.value.remove_watermark_supported ? '支持' : '不支持'
})
const brandExposureSummary = computed(() => {
  if (!growthLoopPresent.value) return ''
  return growthLoop.value.brand_exposure ? '有' : '无'
})
const exportSummary = computed(() => {
  if (!growthLoopPresent.value) return ''
  return growthLoop.value.export_supported ? '支持' : '已预留'
})
const capabilityModeSummary = computed(() => {
  const mode = growthLoop.value?.capability_mode
  if (!mode) return ''
  return mode === 'real' ? 'real · 真实生成' : 'fallback_preview · 预览'
})

// 生成器 QA 摘要（来自 generator-qa-report.json，pipeline 接入时才有）
const generatorQaSummary = computed(() => {
  const gq: any = props.job?.artifacts?.['generator-qa-report.json']
  if (!gq) return ''
  return gq.passed ? '生成器 QA 通过' : '生成器 QA 未通过'
})

const growthSummary = computed(() => {
  const hasGrowth = !!props.job?.artifacts?.['growth-plan.md']
  const hasShare = !!props.job?.artifacts?.['share-strategy.md']
  if (hasGrowth && hasShare) return '增长方案已生成'
  if (hasGrowth || hasShare) return '增长方案不完整'
  return ''
})

// 生成交互闭环 + 传播链路摘要（来自 growth-qa-report.json 的结构检查）
const generationFlowSummary = computed(() => {
  const g: any = props.job?.artifacts?.['growth-qa-report.json']
  if (!g?.checks) return ''
  const c = g.checks
  const flowOk = c.generation_service_exists && c.form_calls_generation && c.generation_template_aware
  const chainOk = c.result_has_share_cta && c.result_has_unlock_hook && c.result_has_watermark
  if (flowOk && chainOk) return '生成闭环 + 传播链路就绪'
  if (flowOk) return '生成闭环就绪，传播链路待补'
  if (chainOk) return '传播链路就绪，生成闭环待补'
  return '生成闭环未就绪'
})

const statusSummary = computed(() => {
  if (!props.job) return '等待启动任务'
  const readiness = props.job.artifacts?.['submission-readiness-report.json']
  const qa = props.job.artifacts?.['qa-report.json']
  const failed = steps.value.find(s => s.status === 'failed')
  if (props.running && currentStep.value) {
    return `系统正在执行 ${currentStep.value.name || currentStep.value.step || currentStep.value.capability || '当前步骤'}：处理中。`
  }
  if (failed) {
    return `任务失败：${failed.name || failed.step || failed.capability} ${failed.error || '执行未通过'}，请查看失败原因。`
  }
  if (qa?.passed && readiness?.is_ready_to_submit) {
    return '任务已完成，当前已满足提交条件，可以进入提交中心。'
  }
  if (qa?.passed) {
    const blocking = readiness?.blocking_issues?.length || 0
    return `任务已完成，但暂不可提交：${blocking} 项阻塞（缺少平台授权或配置）。`
  }
  if (completedCount.value === totalCount.value) {
    return '所有步骤已执行完成。'
  }
  return '等待启动任务'
})
</script>

<template>
  <div class="factory-console">
    <!-- Status bar -->
    <div class="status-bar">
      <div class="status-item" v-if="appName">
        <span class="status-label">应用</span>
        <span class="status-value">{{ appName }}</span>
      </div>
      <div class="status-item" v-if="jobMode">
        <span class="status-label">模式</span>
        <span class="status-value">{{ jobMode }}</span>
      </div>
      <div class="status-item" v-if="job">
        <span class="status-label">Job</span>
        <span class="status-value mono">{{ job.id.slice(0, 8) }}</span>
      </div>
      <div class="status-item" v-if="viralSummary">
        <span class="status-label">Viral</span>
        <span class="status-value">{{ viralSummary }}</span>
      </div>
      <div class="status-item" v-if="templateSummary">
        <span class="status-label">模板</span>
        <span class="status-value mono">{{ templateSummary }}</span>
      </div>
      <div class="status-item" v-if="previewTypeSummary">
        <span class="status-label">预览类型</span>
        <span class="status-value mono">{{ previewTypeSummary }}</span>
      </div>
      <div class="status-item" v-if="templateStatusSummary">
        <span class="status-label">模板状态</span>
        <span class="status-value">{{ templateStatusSummary }}</span>
      </div>
      <div class="status-item" v-if="generationBackendSummary">
        <span class="status-label">生成后端</span>
        <span class="status-value mono">{{ generationBackendSummary }}</span>
      </div>
      <div class="status-item" v-if="realGenerationSummary">
        <span class="status-label">生成方式</span>
        <span class="status-value">{{ realGenerationSummary }}</span>
      </div>
      <div class="status-item" v-if="shareCtaSummary" data-testid="gl-share">
        <span class="status-label">分享 CTA</span>
        <span class="status-value">{{ shareCtaSummary }}</span>
      </div>
      <div class="status-item" v-if="unlockSummary" data-testid="gl-unlock">
        <span class="status-label">解锁</span>
        <span class="status-value">{{ unlockSummary }}</span>
      </div>
      <div class="status-item" v-if="watermarkSummary" data-testid="gl-watermark">
        <span class="status-label">水印</span>
        <span class="status-value">{{ watermarkSummary }}</span>
      </div>
      <div class="status-item" v-if="removeWatermarkSummary" data-testid="gl-remove-watermark">
        <span class="status-label">去水印</span>
        <span class="status-value">{{ removeWatermarkSummary }}</span>
      </div>
      <div class="status-item" v-if="brandExposureSummary" data-testid="gl-brand">
        <span class="status-label">品牌露出</span>
        <span class="status-value">{{ brandExposureSummary }}</span>
      </div>
      <div class="status-item" v-if="exportSummary" data-testid="gl-export">
        <span class="status-label">导出</span>
        <span class="status-value">{{ exportSummary }}</span>
      </div>
      <div class="status-item" v-if="capabilityModeSummary" data-testid="gl-capability">
        <span class="status-label">当前能力</span>
        <span class="status-value">{{ capabilityModeSummary }}</span>
      </div>
      <div class="status-item" v-if="blueprintSummary">
        <span class="status-label">蓝图</span>
        <span class="status-value">{{ blueprintSummary }}</span>
      </div>
      <div class="status-item" v-if="generatorQaSummary">
        <span class="status-label">生成器 QA</span>
        <span class="status-value">{{ generatorQaSummary }}</span>
      </div>
      <div class="status-item" v-if="growthSummary">
        <span class="status-label">增长</span>
        <span class="status-value">{{ growthSummary }}</span>
      </div>
      <div class="status-item" v-if="generationFlowSummary">
        <span class="status-label">闭环</span>
        <span class="status-value">{{ generationFlowSummary }}</span>
      </div>
      <div class="status-item">
        <span class="status-label">进度</span>
        <span class="status-value">{{ completedCount }}/{{ totalCount }}</span>
      </div>
      <div class="status-item" v-if="currentStep">
        <span class="status-label">当前</span>
        <span class="status-value running-text">{{ currentStep.name }}</span>
      </div>
      <div class="status-dot-wrapper" v-if="running">
        <span class="status-dot-running"></span>
        <span class="status-running-label">运行中</span>
      </div>
    </div>

    <!-- Summary sentence -->
    <div class="summary-sentence" v-if="statusSummary !== '等待启动任务'">{{ statusSummary }}</div>
    <div class="boundary-note" v-if="boundaryNoteSummary">能力边界：{{ boundaryNoteSummary }}</div>

    <!-- Main content area -->
    <div class="console-body">
      <div class="timeline-col">
        <StepTimeline
          :steps="steps"
          :selected-id="selectedStepId"
          @select="emit('select-step', $event)"
        />
      </div>
      <div class="detail-col">
        <StepDetailPanel :step="selectedStep" />
      </div>
    </div>

    <!-- Terminal drawer -->
    <TerminalDrawer
      :logs="logs"
      :open="drawerOpen"
      @toggle="drawerOpen = !drawerOpen"
    />
  </div>
</template>

<style scoped>
.factory-console {
  animation: fadeIn 0.3s var(--ease-apple);
}

.summary-sentence {
  font-size: 13px;
  color: var(--color-text-2);
  padding: 8px 16px;
  background: var(--color-blue-subtle);
  border-radius: var(--radius-sm);
  margin-bottom: 16px;
}

.boundary-note {
  font-size: 12px;
  color: var(--color-text-3);
  padding: 6px 16px;
  margin-top: -8px;
  margin-bottom: 16px;
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  background: var(--color-surface-solid);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-3);
  text-transform: uppercase;
}

.status-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-1);
}

.status-value.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.running-text {
  color: var(--color-blue);
}

.status-dot-wrapper {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.status-dot-running {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-green);
  box-shadow: 0 0 6px rgba(52, 199, 89, 0.4);
  animation: pulse 1.5s infinite;
}

.status-running-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-green);
}

.console-body {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 20px;
  min-height: 360px;
}

.timeline-col {
  overflow-y: auto;
  max-height: 480px;
}

.detail-col {
  min-width: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
