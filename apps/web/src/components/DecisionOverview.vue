<script setup lang="ts">
import { computed } from 'vue'
import type { JobDetail } from '../types/job'

const props = defineProps<{
  job: JobDetail | null
}>()

const opportunity = computed(() => {
  return props.job?.artifacts?.['opportunity-report.json'] || null
})

const viral = computed(() => {
  return props.job?.artifacts?.['viral-score.json'] || null
})

const templateSelection = computed(() => {
  return props.job?.artifacts?.['template-selection.json'] || null
})

// 传播闭环摘要（来自 generator-source.json.growth_loop / growth_loop_summary，P0-2）。
const growthLoop = computed<Record<string, any>>(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.growth_loop || {}
})
const growthLoopSummary = computed<Record<string, any>>(() => {
  const gs: any = props.job?.artifacts?.['generator-source.json']
  return gs?.growth_loop_summary || gs?.codegen_report || {}
})
const hasGrowthLoop = computed(() =>
  !!growthLoopSummary.value?.growth_loop_present || !!Object.keys(growthLoop.value).length,
)
const isPreviewMode = computed(() => {
  const mode = growthLoop.value?.capability_mode || growthLoopSummary.value?.capability_mode
  return mode === 'fallback_preview'
})

const pipelineReport = computed(() => {
  return props.job?.artifacts?.['pipeline-report.json'] || null
})

const submissionReadiness = computed(() => {
  return props.job?.artifacts?.['submission-readiness-report.json'] || null
})


const completionItems = computed(() => {
  if (!pipelineReport.value?.steps) return []
  return pipelineReport.value.steps.map((s: any) => ({
    name: s.name,
    done: s.status === 'passed' || s.status === 'done',
  }))
})

const nextActions = computed(() => {
  const actions: { type: string; text: string }[] = []
  if (submissionReadiness.value?.blocking?.length) {
    for (const b of submissionReadiness.value.blocking) {
      actions.push({ type: 'human', text: b })
    }
  }
  if (submissionReadiness.value?.warnings?.length) {
    for (const w of submissionReadiness.value.warnings) {
      actions.push({ type: 'system', text: w })
    }
  }
  if (actions.length === 0 && submissionReadiness.value?.is_ready) {
    actions.push({ type: 'system', text: '所有检查已通过，可以提交上架' })
  }
  return actions
})
</script>

<template>
  <div class="decision-overview">
    <!-- Card 1: Opportunity Score -->
    <div class="card">
      <h3 class="card-title">机会评分</h3>
      <div v-if="opportunity" class="card-body">
        <div class="score-row">
          <span class="score-number">{{ opportunity.total_score ?? opportunity.opportunity_score ?? opportunity.score ?? '--' }}</span>
          <span class="score-max">/ 100</span>
          <span
            class="score-badge"
            :class="{
              'badge--green': (opportunity.recommendation || '').includes('推荐') || (opportunity.recommendation || '').toLowerCase().includes('go'),
              'badge--orange': (opportunity.recommendation || '').includes('谨慎'),
              'badge--red': (opportunity.recommendation || '').includes('不')
            }"
          >{{ opportunity.recommendation || '待评估' }}</span>
        </div>
        <div v-if="opportunity.reasons?.length" class="reasons">
          <div v-for="(r, i) in opportunity.reasons" :key="i" class="reason-item">
            <span class="reason-bullet">{{ Number(i) + 1 }}.</span>
            <span>{{ r }}</span>
          </div>
        </div>
        <div v-if="opportunity.dimensions" class="dimensions">
          <div v-for="(val, key) in opportunity.dimensions" :key="String(key)" class="dim-item">
            <span class="dim-label">{{ key }}</span>
            <span class="dim-value">{{ val }}</span>
          </div>
        </div>
      </div>
      <div v-else class="card-empty">暂无数据</div>
    </div>

    <!-- Card 1b: Viral Decision -->
    <div class="card">
      <h3 class="card-title">传播型决策</h3>
      <div v-if="viral" class="card-body">
        <div class="score-row">
          <span class="score-number">{{ viral.viral_score ?? '--' }}</span>
          <span class="score-max">/ 100</span>
          <span class="score-badge badge--green">{{ viral.tier || 'unknown' }}</span>
        </div>
        <div class="dimensions">
          <div v-for="(val, key) in viral.dimensions" :key="String(key)" class="dim-item">
            <span class="dim-label">{{ key }}</span>
            <span class="dim-value">{{ val }}</span>
          </div>
        </div>
        <div v-if="templateSelection" class="template-line">
          模板：{{ templateSelection.selected_template }} · {{ templateSelection.theme_label }}
        </div>
      </div>
      <div v-else class="card-empty">暂无数据</div>
    </div>

    <!-- Card 1c: Growth Loop Impact（传播闭环影响） -->
    <div class="card" data-testid="growth-loop-card">
      <h3 class="card-title">传播闭环影响</h3>
      <div v-if="hasGrowthLoop" class="card-body">
        <div class="gl-share-title" v-if="growthLoop.share_title">{{ growthLoop.share_title }}</div>
        <div class="gl-share-copy" v-if="growthLoop.share_copy">{{ growthLoop.share_copy }}</div>
        <div class="gl-lines">
          <div class="gl-line" v-if="growthLoop.unlock_hint">
            <span class="gl-line-key">解锁</span><span>{{ growthLoop.unlock_hint }}</span>
          </div>
          <div class="gl-line">
            <span class="gl-line-key">水印 / 去水印</span>
            <span>{{ (growthLoopSummary.has_watermark ?? growthLoop.has_watermark) ? '有水印' : '无水印' }}
              · {{ (growthLoopSummary.remove_watermark_supported ?? growthLoop.remove_watermark_supported) ? '支持去水印' : '暂不支持' }}</span>
          </div>
          <div class="gl-line">
            <span class="gl-line-key">导出</span>
            <span>{{ (growthLoopSummary.export_supported ?? growthLoop.export_supported) ? (growthLoop.export_label || '支持导出') : '导出入口已预留' }}</span>
          </div>
        </div>
        <div class="gl-capability" :class="isPreviewMode ? 'gl-capability--preview' : 'gl-capability--real'">
          {{ isPreviewMode ? 'fallback_preview · 预览模式' : 'real · 真实生成' }}
        </div>
        <div class="gl-preview-hint" v-if="isPreviewMode">
          ⚠ 当前为预览/脚本/卡片结果，非真实视频生成；分享与导出的是预览结果。
        </div>
      </div>
      <div v-else class="card-empty">暂无传播闭环数据</div>
    </div>

    <!-- Card 2: Completion Checklist -->
    <div class="card">
      <h3 class="card-title">完成度检查</h3>
      <div v-if="completionItems.length" class="card-body">
        <div class="checklist">
          <div v-for="item in completionItems" :key="item.name" class="check-item">
            <span class="check-icon" :class="item.done ? 'check--done' : 'check--pending'">
              {{ item.done ? '✓' : '○' }}
            </span>
            <span class="check-text" :class="{ 'text--done': item.done }">{{ item.name }}</span>
          </div>
        </div>
        <div class="checklist-summary">
          {{ completionItems.filter((i: any) => i.done).length }} / {{ completionItems.length }} 步骤完成
        </div>
      </div>
      <div v-else class="card-empty">该任务未生成流水线报告</div>
    </div>

    <!-- Card 3: Submission Readiness -->
    <div class="card">
      <h3 class="card-title">提交就绪度</h3>
      <div v-if="submissionReadiness" class="card-body">
        <div class="ready-status">
          <span class="ready-dot" :class="(submissionReadiness.is_ready_to_submit || submissionReadiness.is_ready) ? 'dot--green' : 'dot--orange'"></span>
          <span class="ready-text">{{ (submissionReadiness.is_ready_to_submit || submissionReadiness.is_ready) ? '就绪，可以提交' : '尚未就绪' }}</span>
        </div>
        <div v-if="(submissionReadiness.blocking_issues || submissionReadiness.blocking)?.length" class="block-list">
          <h4 class="sub-heading">阻塞项</h4>
          <div v-for="(b, i) in (submissionReadiness.blocking_issues || submissionReadiness.blocking || [])" :key="i" class="block-item block-item--red">
            {{ b }}
          </div>
        </div>
        <div v-if="(submissionReadiness.warning_issues || submissionReadiness.warnings)?.length" class="block-list">
          <h4 class="sub-heading">警告</h4>
          <div v-for="(w, i) in (submissionReadiness.warning_issues || submissionReadiness.warnings || [])" :key="i" class="block-item block-item--orange">
            {{ w }}
          </div>
        </div>
      </div>
      <div v-else class="card-empty">暂无数据</div>
    </div>

    <!-- Card 4: Next Actions -->
    <div class="card">
      <h3 class="card-title">下一步行动</h3>
      <div v-if="nextActions.length" class="card-body">
        <div v-for="(action, i) in nextActions" :key="i" class="action-item">
          <span class="action-type" :class="action.type === 'human' ? 'type--human' : 'type--system'">
            {{ action.type === 'human' ? '人工' : '系统' }}
          </span>
          <span class="action-text">{{ action.text }}</span>
        </div>
      </div>
      <div v-else class="card-empty">暂无数据</div>
    </div>
  </div>
</template>

<style scoped>
.decision-overview {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  animation: fadeIn 0.3s var(--ease-apple);
}

.card {
  background: var(--color-surface-solid);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 20px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-1);
  margin-bottom: 14px;
}

.card-body {
  font-size: 13px;
}

.card-empty {
  font-size: 13px;
  color: var(--color-text-3);
  padding: 20px 0;
  text-align: center;
}

/* Score card */
.score-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 12px;
}
.score-number {
  font-size: 32px;
  font-weight: 700;
  color: var(--color-text-1);
}
.score-max {
  font-size: 14px;
  color: var(--color-text-3);
}
.score-badge {
  margin-left: 12px;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 980px;
  background: rgba(0, 0, 0, 0.04);
  color: var(--color-text-2);
}
.badge--green { background: var(--color-green-subtle); color: #166534; }
.badge--orange { background: var(--color-orange-subtle); color: #92400e; }
.badge--red { background: rgba(255, 59, 48, 0.08); color: #991b1b; }

.reasons { margin-top: 8px; }
.reason-item {
  display: flex;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-2);
  padding: 3px 0;
}
.reason-bullet { color: var(--color-text-3); font-weight: 600; }

.dimensions { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }
.dim-item { font-size: 12px; background: rgba(0,0,0,0.03); padding: 3px 8px; border-radius: 4px; }
.dim-label { color: var(--color-text-3); margin-right: 4px; }
.dim-value { color: var(--color-text-1); font-weight: 500; }
.template-line { margin-top: 12px; font-size: 12px; color: var(--color-text-2); }

/* Growth Loop Impact */
.gl-share-title { font-size: 14px; font-weight: 600; color: var(--color-text-1); margin-bottom: 4px; }
.gl-share-copy { font-size: 12px; color: var(--color-text-2); margin-bottom: 10px; line-height: 1.5; }
.gl-lines { display: flex; flex-direction: column; gap: 5px; margin-bottom: 10px; }
.gl-line { display: flex; gap: 8px; font-size: 12px; color: var(--color-text-1); }
.gl-line-key { color: var(--color-text-3); flex-shrink: 0; min-width: 72px; }
.gl-capability { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 10px; border-radius: 980px; }
.gl-capability--real { background: var(--color-green-subtle); color: #166534; }
.gl-capability--preview { background: var(--color-orange-subtle); color: #92400e; }
.gl-preview-hint { margin-top: 8px; font-size: 11px; color: #a8071a; line-height: 1.5; }

/* Checklist */
.checklist { display: flex; flex-direction: column; gap: 4px; }
.check-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.check-icon { width: 18px; text-align: center; font-size: 13px; }
.check--done { color: var(--color-green); }
.check--pending { color: var(--color-text-3); }
.check-text { font-size: 13px; color: var(--color-text-1); }
.text--done { color: var(--color-text-2); }
.checklist-summary {
  margin-top: 10px;
  font-size: 12px;
  color: var(--color-text-3);
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}

/* Readiness */
.ready-status { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.ready-dot { width: 10px; height: 10px; border-radius: 50%; }
.dot--green { background: var(--color-green); }
.dot--orange { background: var(--color-orange); }
.ready-text { font-size: 14px; font-weight: 500; color: var(--color-text-1); }

.block-list { margin-top: 8px; }
.sub-heading { font-size: 11px; font-weight: 600; color: var(--color-text-3); margin-bottom: 4px; text-transform: uppercase; }
.block-item { font-size: 12px; padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; }
.block-item--red { background: rgba(255, 59, 48, 0.06); color: #991b1b; }
.block-item--orange { background: var(--color-orange-subtle); color: #92400e; }

/* Actions */
.action-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.action-type {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
  flex-shrink: 0;
}
.type--human { background: var(--color-orange-subtle); color: #92400e; }
.type--system { background: var(--color-blue-subtle); color: var(--color-blue); }
.action-text { font-size: 13px; color: var(--color-text-1); }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>


