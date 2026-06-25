<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TaskItem, TaskSummary, TaskHealth } from '../types/job'

const props = defineProps<{
  summary: TaskSummary | null
  tasks: TaskItem[]
  busyTaskId: string
  health?: TaskHealth | null
}>()

const emit = defineEmits<{
  refresh: []
  cancel: [taskId: string]
  retry: [taskId: string]
  'select-job': [jobId: string]
}>()

// 任务系统的五种状态，按生命周期排序，缺省补 0，让概览始终结构稳定。
const STATUS_ORDER: { key: string; label: string }[] = [
  { key: 'pending', label: '等待中' },
  { key: 'running', label: '执行中' },
  { key: 'succeeded', label: '已成功' },
  { key: 'failed', label: '已失败' },
  { key: 'cancelled', label: '已取消' },
]

const KIND_LABEL: Record<string, string> = {
  'pipeline.run': '生成（消费队列）',
  'pipeline.auto': '一键抓取+生成',
  'opportunity.crawl': '抓取机会',
}

// 当前筛选状态：'all' 看全部，否则只看该状态。点概览卡片切换（本地过滤，即时）。
const activeFilter = ref<string>('all')
function setFilter(key: string) {
  activeFilter.value = key
}

const statusTiles = computed(() =>
  STATUS_ORDER.map((s) => ({
    ...s,
    count: props.summary?.by_status?.[s.key] ?? 0,
  })),
)

const total = computed(() => props.summary?.total ?? 0)

// 按当前筛选过滤任务列表；'all' 直接返回全部。
const visibleTasks = computed(() =>
  activeFilter.value === 'all'
    ? props.tasks
    : props.tasks.filter((t) => t.status === activeFilter.value),
)


function statusLabel(status: string) {
  return STATUS_ORDER.find((s) => s.key === status)?.label || status
}

function kindLabel(kind: string) {
  return KIND_LABEL[kind] || kind
}

function shortId(id?: string | null) {
  if (!id) return '--'
  return id.length > 10 ? id.slice(0, 8) : id
}

function timeText(iso?: string | null) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// 终态任务不可取消；失败任务可重试。运行中/等待中可取消。
function canCancel(t: TaskItem) {
  return t.status === 'pending' || t.status === 'running'
}
function canRetry(t: TaskItem) {
  return t.status === 'failed'
}
</script>

<template>
  <div class="task-panel">
    <div class="panel-head">
      <div>
        <span class="eyebrow">Task Queue</span>
        <h2>任务队列：每一次生成都在这里被追踪。</h2>
        <p class="head-copy">
          点「立即生成」会创建一个持久化任务（pipeline.run），由后台 worker 消费指定机会。
          状态、重试、取消都在这条队列里。
        </p>
      </div>
      <button class="ghost" @click="emit('refresh')">刷新</button>
    </div>

    <div class="summary-row">
      <button
        type="button"
        class="summary-tile summary-tile--total"
        :class="{ 'summary-tile--selected': activeFilter === 'all' }"
        @click="setFilter('all')"
      >
        <span>全部任务</span>
        <strong>{{ total }}</strong>
      </button>
      <button
        v-for="tile in statusTiles"
        :key="tile.key"
        type="button"
        class="summary-tile"
        :class="[`summary-tile--${tile.key}`, { 'summary-tile--selected': activeFilter === tile.key }]"
        @click="setFilter(tile.key)"
      >
        <span>{{ tile.label }}</span>
        <strong>{{ tile.count }}</strong>
      </button>
    </div>

    <div v-if="props.health" class="queue-health" data-testid="queue-health">
      <span>活跃 worker：{{ props.health.active_worker_count }}</span>
      <span>最老等待：{{ props.health.oldest_pending_seconds }}s</span>
      <span>执行中：{{ props.health.running_count }}</span>
    </div>

    <div v-if="visibleTasks.length" class="task-list" data-testid="task-list">
      <div
        v-for="t in visibleTasks"
        :key="t.id"
        class="task-row"
        :class="{ 'task-row--active': t.status === 'running' }"
      >
        <div class="task-main">
          <div class="task-title">
            <span class="status-dot" :class="`dot--${t.status}`"></span>
            <strong>{{ kindLabel(t.kind) }}</strong>
            <span class="status-badge" :class="`badge--${t.status}`">{{ statusLabel(t.status) }}</span>
          </div>
          <div class="task-meta">
            <span class="meta-item">任务 <em class="mono">{{ shortId(t.id) }}</em></span>
            <span class="meta-item" v-if="t.queue_id">机会 <em class="mono">{{ t.queue_id }}</em></span>
            <button
              class="meta-item meta-item--link"
              v-if="t.job_id"
              @click="emit('select-job', t.job_id!)"
            >Job <em class="mono">{{ shortId(t.job_id) }}</em></button>
            <span class="meta-item">尝试 {{ t.attempts }}/{{ t.max_attempts }}</span>
          </div>
          <div class="task-error" v-if="t.error_message">{{ t.error_message }}</div>
        </div>
        <div class="task-side">
          <span class="task-time" v-if="timeText(t.updated_at)">{{ timeText(t.updated_at) }}</span>
          <div class="task-actions">
            <button
              v-if="canCancel(t)"
              class="task-btn"
              :disabled="busyTaskId === t.id"
              @click="emit('cancel', t.id)"
            >取消</button>
            <button
              v-if="canRetry(t)"
              class="task-btn task-btn--primary"
              :disabled="busyTaskId === t.id"
              @click="emit('retry', t.id)"
            >重试</button>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="tasks.length" class="empty-state" data-testid="task-empty-filtered">
      <strong>没有{{ statusLabel(activeFilter) }}的任务</strong>
      <span>当前筛选下没有任务。点「全部任务」查看所有任务。</span>
    </div>

    <div v-else class="empty-state" data-testid="task-empty">
      <strong>还没有任务</strong>
      <span>在「机会工厂」里对某条机会点「立即生成」，就会在这里出现一个任务。</span>
      <code>python -m core.pipeline.task_worker --worker-id worker-local</code>
    </div>
  </div>
</template>

<style scoped>
.ghost:hover { background: #ececf1; }

.summary-row {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-top: 24px;
}

.summary-tile {
  padding: 16px;
  border-radius: 20px;
  background: linear-gradient(180deg, #fbfbfd 0%, #f4f4f6 100%);
  display: flex;
  flex-direction: column;
  gap: 8px;
  text-align: left;
  border: 2px solid transparent;
  cursor: pointer;
  font: inherit;
  transition: transform 0.15s var(--ease-apple), box-shadow 0.15s var(--ease-apple), border-color 0.15s;
}
.summary-tile:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0,0,0,0.08); }
.summary-tile:active { transform: translateY(0); }
/* 选中态：深色描边凸显当前筛选；total 用浅色描边以在黑底上可见。 */
.summary-tile--selected { border-color: #1d1d1f; }
.summary-tile--total.summary-tile--selected { border-color: rgba(255,255,255,0.55); }
.summary-tile span { color: #6e6e73; font-size: 12px; font-weight: 600; }
.summary-tile strong { font-size: 30px; font-weight: 700; letter-spacing: -0.04em; line-height: 1; }
.summary-tile--total { background: #1d1d1f; }
.summary-tile--total span { color: rgba(255, 255, 255, 0.7); }
.summary-tile--total strong { color: #fff; }
.summary-tile--running strong { color: #0071e3; }
.summary-tile--succeeded strong { color: #1a7f37; }
.summary-tile--failed strong { color: #c41e16; }
.summary-tile--cancelled strong { color: #8a8a8e; }

.queue-health {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 13px;
  color: #6b6b70;
}
.queue-health span { white-space: nowrap; }

.task-list {
  margin-top: 22px;
  display: grid;
  gap: 10px;
}

.task-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 18px;
  background: #f5f5f7;
}
.task-row--active {
  background: linear-gradient(180deg, rgba(0, 113, 227, 0.08), rgba(255, 255, 255, 0.9));
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.16);
}

.task-title { display: flex; align-items: center; gap: 8px; }
.task-title strong { font-size: 15px; }

.status-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.dot--pending { background: #c7c7cc; }
.dot--running { background: #0071e3; box-shadow: 0 0 6px rgba(0, 113, 227, 0.4); animation: pulse 1.5s infinite; }
.dot--succeeded { background: #34c759; }
.dot--failed { background: #ff3b30; }
.dot--cancelled { background: #8a8a8e; }

.status-badge { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 980px; }
.badge--pending { background: rgba(0,0,0,0.05); color: #6e6e73; }
.badge--running { background: rgba(0, 113, 227, 0.1); color: #0071e3; }
.badge--succeeded { background: var(--color-green-subtle); color: #166534; }
.badge--failed { background: rgba(255, 59, 48, 0.08); color: #991b1b; }
.badge--cancelled { background: rgba(0,0,0,0.05); color: #8a8a8e; }

.task-meta { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 8px; }
.meta-item { font-size: 12px; color: #6e6e73; }
.meta-item .mono { font-family: var(--font-mono); font-style: normal; color: #1d1d1f; }
.meta-item--link { background: none; border: none; padding: 0; cursor: pointer; }
.meta-item--link:hover .mono { color: #0071e3; }

.task-error {
  margin-top: 8px;
  font-size: 12px;
  color: #991b1b;
  background: rgba(255, 59, 48, 0.06);
  padding: 6px 10px;
  border-radius: 8px;
  line-height: 1.5;
  word-break: break-word;
}

.task-side { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; flex-shrink: 0; }
.task-time { font-size: 11px; color: #8a8a8e; }
.task-actions { display: flex; gap: 6px; }
.task-btn {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid rgba(0,0,0,0.1);
  background: #fff;
  color: #1d1d1f;
  cursor: pointer;
}
.task-btn:hover:not(:disabled) { background: #f0f0f2; }
.task-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.task-btn--primary { background: #0071e3; color: #fff; border-color: #0071e3; }
.task-btn--primary:hover:not(:disabled) { background: #0060c0; }

.empty-state {
  margin-top: 22px;
  padding: 30px;
  border-radius: 22px;
  background: #f5f5f7;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.empty-state strong { font-size: 16px; }
.empty-state span { color: #6e6e73; font-size: 13px; }
.empty-state code {
  margin-top: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: #6e6e73;
  background: rgba(0,0,0,0.04);
  padding: 8px 12px;
  border-radius: 8px;
}

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

@media (max-width: 980px) {
  .summary-row { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .panel-head { flex-direction: column; }
  .task-row { flex-direction: column; }
  .task-side { align-items: flex-start; }
}

.task-panel {
  margin-top: 18px;
  padding: 30px;
  border-radius: 30px;
  background: #ffffff;
  box-shadow: var(--shadow-card);
  animation: fadeIn 0.3s var(--ease-apple);
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}

.eyebrow {
  color: #6e6e73;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.panel-head h2 {
  margin-top: 8px;
  font-size: clamp(24px, 3vw, 36px);
  line-height: 1.06;
  letter-spacing: -0.04em;
}

.head-copy {
  margin-top: 12px;
  max-width: 560px;
  color: #6e6e73;
  font-size: 13px;
  line-height: 1.55;
}

.ghost {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 9px 18px;
  background: #f5f5f7;
  color: #1d1d1f;
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
}
.ghost:hover { background: #ececf1; }
</style>

