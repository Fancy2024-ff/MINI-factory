<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import type {
  JobSummary,
  JobDetail,
  OpportunitySummary,
  OpportunityView,
  PipelineLaunchOptions,
  PipelineMode,
  PipelineStep,
  TaskItem,
  TaskSummary,
} from './types/job'
import { api, connectPipelineWS, type WSHandle } from './services/api'
import AppleTopNav from './components/AppleTopNav.vue'
import JobMegaMenu from './components/JobMegaMenu.vue'
import SegmentedTabs from './components/SegmentedTabs.vue'
import FactoryConsole from './components/FactoryConsole.vue'
import DecisionOverview from './components/DecisionOverview.vue'
import DeliverablesPanel from './components/DeliverablesPanel.vue'
import SubmitCenterPanel from './components/SubmitCenterPanel.vue'
import PlatformsPanel from './components/PlatformsPanel.vue'
import OpportunityBoard from './components/OpportunityBoard.vue'
import OpportunityExplorer from './components/OpportunityExplorer.vue'
import TaskQueuePanel from './components/TaskQueuePanel.vue'

const jobs = ref<JobSummary[]>([])
const currentJob = ref<JobDetail | null>(null)
const opportunitySummary = ref<OpportunitySummary | null>(null)
const opportunityQueue = ref<any[]>([])
const opportunityCandidates = ref<any[]>([])
const opportunityFeatures = ref<any[]>([])
const opportunityView = ref<OpportunityView>('queue')
const menuOpen = ref(false)
const running = ref(false)
const currentTaskId = ref('')
const logs = ref<string[]>([])
const activeTab = ref('overview')
const error = ref('')
const notice = ref('')
const wsStatus = ref('')
const mode = ref<PipelineMode>('auto')
const runtimePipelineSteps = ref<PipelineStep[]>([])
const selectedStepId = ref('')
// 生产任务系统视图状态（只读 + cancel/retry；底层逻辑在后端，不在前端）。
const tasks = ref<TaskItem[]>([])
const taskSummary = ref<TaskSummary | null>(null)
const busyTaskId = ref('')
const launchOptions = ref<PipelineLaunchOptions>({
  regions: 'CN,US',
  platforms: 'app_store',
  limit: 10,
  max_generate: 1,
})

function setMode(value: PipelineMode) {
  mode.value = value
}

function setOpportunityView(value: OpportunityView) {
  opportunityView.value = value
  activeTab.value = 'opportunities'
}

function updateLaunchOptions(next: PipelineLaunchOptions) {
  launchOptions.value = next
}

let wsHandle: WSHandle | null = null
let statusTimer: ReturnType<typeof setInterval> | null = null
let tasksTimer: ReturnType<typeof setInterval> | null = null

// 任务有「进行中/等待中」时持续轮询，让队列状态在演示时自动推进。
function hasActiveTasks() {
  const s = taskSummary.value?.by_status
  if (!s) return false
  return (s.pending || 0) > 0 || (s.running || 0) > 0
}

function startTaskPolling() {
  if (tasksTimer) return
  tasksTimer = setInterval(async () => {
    // 仅在任务页可见或仍有活跃任务时刷新，避免无意义轮询。
    if (activeTab.value === 'tasks' || hasActiveTasks()) {
      await loadTasks()
    } else {
      stopTaskPolling()
    }
  }, 4000)
}

function stopTaskPolling() {
  if (tasksTimer) {
    clearInterval(tasksTimer)
    tasksTimer = null
  }
}

const tabs = [
  { id: 'overview', label: '机会工厂' },
  { id: 'opportunities', label: '机会数据' },
  { id: 'tasks', label: '任务队列' },
  { id: 'console', label: '生产日志' },
  { id: 'decision', label: '决策总览' },
  { id: 'deliverables', label: '交付物' },
  { id: 'submit', label: '提交中心' },
  { id: 'platforms', label: '平台库' },
]

async function loadJobs() {
  try {
    const res = await api.getJobs()
    jobs.value = res.jobs
  } catch (e: any) {
    error.value = '后端连接失败: ' + e.message
  }
}

async function loadLatest() {
  try {
    currentJob.value = await api.getLatestJob()
  } catch (e: any) {
    if (e?.status !== 404) {
      error.value = '无法连接后端: ' + e.message
    }
  }
}

async function loadOpportunitySummary() {
  try {
    opportunitySummary.value = await api.getOpportunitySummary()
  } catch (e: any) {
    if (!currentJob.value) error.value = '机会数据读取失败: ' + e.message
  }
}

async function loadOpportunityDetails() {
  try {
    const [queue, candidates, features] = await Promise.all([
      api.getOpportunityQueue(),
      api.getOpportunityCandidates(),
      api.getOpportunityFeatures(),
    ])
    opportunityQueue.value = queue.items || []
    opportunityCandidates.value = candidates.items || []
    opportunityFeatures.value = features.items || []
  } catch (e: any) {
    if (!opportunitySummary.value) error.value = '机会明细读取失败: ' + e.message
  }
}

async function refreshOpportunityData() {
  await loadOpportunitySummary()
  await loadOpportunityDetails()
}

async function loadTasks() {
  try {
    const [list, summary] = await Promise.all([
      api.getTasks({ limit: 50 }),
      api.getTaskSummary(),
    ])
    tasks.value = list.tasks || []
    taskSummary.value = summary
  } catch (e: any) {
    // 任务库为空或后端未起也不该污染主错误条，仅在确无其它数据时提示。
    if (!opportunitySummary.value && !currentJob.value) {
      error.value = '任务数据读取失败: ' + e.message
    }
  }
}

async function cancelTask(taskId: string) {
  busyTaskId.value = taskId
  try {
    await api.cancelTask(taskId)
    await loadTasks()
  } catch (e: any) {
    error.value = e.message
  } finally {
    busyTaskId.value = ''
  }
}

async function retryTask(taskId: string) {
  busyTaskId.value = taskId
  try {
    await api.retryTask(taskId)
    await loadTasks()
  } catch (e: any) {
    error.value = e.message
  } finally {
    busyTaskId.value = ''
  }
}

// generate_now 现在创建一个持久化任务（pipeline.run，定向消费该 queue item），不再
// 同步直跑。已有 active task 时后端返回 reused=true，前端提示「复用现有任务」。
async function handleQueueAction(p: { action: 'prioritize' | 'skip' | 'retry' | 'generate_now'; queueId: string }) {
  error.value = ''
  notice.value = ''
  try {
    const res = await api.queueAction(p.action, p.queueId)
    if (p.action === 'generate_now') {
      if (res.reused) {
        notice.value = `该机会已有进行中的任务（${(res.task_id || '').slice(0, 8)}），已复用，不重复创建。`
      } else {
        notice.value = `已创建生成任务 ${(res.task_id || '').slice(0, 8)}，可在「任务队列」查看进度。`
      }
      activeTab.value = 'tasks'
      await loadTasks()
      startTaskPolling()
    }
    await refreshOpportunityData()
  } catch (e: any) {
    error.value = e.message
  }
}

async function selectJob(id: string) {
  menuOpen.value = false
  try {
    currentJob.value = await api.getJob(id)
  } catch (e: any) {
    error.value = e.message
  }
}

function teardownWatchers() {
  if (wsHandle) {
    wsHandle.disconnect()
    wsHandle = null
  }
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
}

function finishRun(jobId?: string) {
  running.value = false
  currentTaskId.value = ''
  wsStatus.value = ''
  teardownWatchers()
  if (jobId) {
    selectJob(jobId)
  }
  loadJobs()
  refreshOpportunityData()
  loadTasks()
}

function startStatusPolling(jobId: string) {
  if (statusTimer) clearInterval(statusTimer)
  statusTimer = setInterval(async () => {
    try {
      const s = await api.getPipelineStatus()
      if (!s.running) finishRun(jobId)
    } catch {
      /* transient backend hiccup - keep polling */
    }
  }, 4000)
}

async function startPipeline(nextMode?: PipelineMode) {
  if (nextMode) mode.value = nextMode
  running.value = true
  error.value = ''
  wsStatus.value = ''
  logs.value = []
  runtimePipelineSteps.value = []
  selectedStepId.value = ''
  activeTab.value = mode.value === 'crawl' ? 'overview' : 'console'
  teardownWatchers()

  try {
    if (mode.value === 'real') {
      const inputs = await api.getRealInputs()
      if (!inputs.exists || inputs.apps.length === 0) {
        error.value = 'Legacy real mode 需要先导入真实 App 数据。'
        running.value = false
        return
      }
    }

    const runOptions = mode.value === 'auto' || mode.value === 'crawl'
      ? launchOptions.value
      : {}
    const res = await api.startPipeline(mode.value, runOptions)
    if (!res.accepted) {
      error.value = 'Pipeline rejected'
      running.value = false
      return
    }
    currentTaskId.value = res.task_id || ''

    if (res.job_id) {
      startStatusPolling(res.job_id)
      wsHandle = connectPipelineWS(res.job_id, {
        onMessage: (msg) => {
          if (msg.type === 'log' || msg.type === 'step_log') {
            logs.value.push(msg.data || msg.message || '')
            if (logs.value.length > 3000) {
              logs.value.splice(0, logs.value.length - 3000)
            }
          }

          if (msg.type === 'step_started') {
            const stepId = msg.step || msg.capability || msg.name || ''
            const step: PipelineStep = {
              step: stepId,
              name: msg.name || msg.step || '',
              capability: msg.capability || stepId,
              status: 'running',
              started_at: msg.started_at,
            }
            runtimePipelineSteps.value.push(step)
            selectedStepId.value = stepId
          }

          if (msg.type === 'step_finished') {
            const stepId = msg.step || msg.capability || msg.name || ''
            const idx = runtimePipelineSteps.value.findIndex(
              (s) => (s.step || s.capability) === stepId
            )
            if (idx >= 0) {
              runtimePipelineSteps.value[idx].status = msg.success === false ? 'failed' : 'passed'
              runtimePipelineSteps.value[idx].artifact = msg.artifact
              runtimePipelineSteps.value[idx].duration_ms = msg.duration_ms
              runtimePipelineSteps.value[idx].finished_at = msg.finished_at
              if (msg.error) runtimePipelineSteps.value[idx].error = msg.error
            }
          }

          if (msg.type === 'pipeline_failed') {
            error.value = '流水线失败: ' + (msg.user_message || msg.error || '未知错误')
            finishRun(msg.job_id)
          }

          if (msg.type === 'pipeline_finished') {
            finishRun(msg.job_id)
          }
        },
        onError: (info) => {
          if (info.code === 4001) {
            error.value = '认证失败，请检查 VITE_API_TOKEN 是否与后端 DASHBOARD_API_KEY 一致'
          }
        },
        onReconnect: (attempt) => {
          wsStatus.value = `连接断开，重试中… (第 ${attempt} 次)`
        },
        onClose: () => {
          wsStatus.value = '实时日志连接已断开，改用状态轮询'
        },
      })
    }
  } catch (e: any) {
    error.value = `API error: ${e.message}`
    running.value = false
    teardownWatchers()
  }
}

function handleSelectStep(stepId: string) {
  selectedStepId.value = stepId
}

async function stopPipeline() {
  try {
    if (currentTaskId.value) {
      // async 主路径：取消 worker 正在执行的 task
      await api.cancelTask(currentTaskId.value)
    } else {
      // sync 兼容路径：终止 API 进程内的子进程
      await api.stopPipeline()
    }
    wsStatus.value = '已请求停止流水线…'
  } catch (e: any) {
    error.value = `停止失败: ${e.message}`
  } finally {
    currentTaskId.value = ''
    finishRun()
  }
}

onMounted(async () => {
  await loadJobs()
  await loadLatest()
  await refreshOpportunityData()
  await loadTasks()
  if (hasActiveTasks()) startTaskPolling()
})

onBeforeUnmount(() => {
  teardownWatchers()
  stopTaskPolling()
})
</script>

<template>
  <div class="app" :class="{ 'app--dimmed': menuOpen }">
    <AppleTopNav
      :current-job="currentJob"
      :running="running"
      :mode="mode"
      @toggle-menu="menuOpen = !menuOpen"
      @start="startPipeline"
      @update:mode="setMode"
    />

    <JobMegaMenu
      v-if="menuOpen"
      :jobs="jobs"
      :current-id="currentJob?.id"
      @select="selectJob"
      @close="menuOpen = false"
    />

    <main class="main" @click="menuOpen = false">
      <div v-if="error" class="error-banner">
        {{ error }}
        <button class="retry-btn" @click="error = ''; loadJobs(); loadLatest(); refreshOpportunityData(); loadTasks()">重试</button>
      </div>

      <div v-if="notice" class="notice-banner">
        {{ notice }}
        <button class="retry-btn" @click="notice = ''">知道了</button>
      </div>

      <div v-if="wsStatus && running" class="ws-banner">{{ wsStatus }}</div>

      <SegmentedTabs :tabs="tabs" v-model="activeTab" />

      <div class="panel-area">
        <OpportunityBoard
          v-if="activeTab === 'overview'"
          :summary="opportunitySummary"
          :current-job="currentJob"
          :running="running"
          :mode="mode"
          :launch-options="launchOptions"
          @start="startPipeline"
          @stop="stopPipeline"
          @refresh="refreshOpportunityData"
          @open-view="setOpportunityView"
          @update-launch-options="updateLaunchOptions"
          @queue-action="handleQueueAction"
        />
        <OpportunityExplorer
          v-if="activeTab === 'opportunities'"
          :queue="opportunityQueue"
          :candidates="opportunityCandidates"
          :features="opportunityFeatures"
          :selected-view="opportunityView"
          @update:selected-view="setOpportunityView"
        />
        <TaskQueuePanel
          v-if="activeTab === 'tasks'"
          :summary="taskSummary"
          :tasks="tasks"
          :busy-task-id="busyTaskId"
          @refresh="loadTasks"
          @cancel="cancelTask"
          @retry="retryTask"
          @select-job="selectJob"
        />
        <FactoryConsole
          v-if="activeTab === 'console'"
          :job="currentJob"
          :running="running"
          :logs="logs"
          :runtime-pipeline-steps="runtimePipelineSteps"
          :selected-step-id="selectedStepId"
          @select-step="handleSelectStep"
        />
        <DecisionOverview v-if="activeTab === 'decision'" :job="currentJob" />
        <DeliverablesPanel v-if="activeTab === 'deliverables'" :job="currentJob" />
        <SubmitCenterPanel v-if="activeTab === 'submit'" />
        <PlatformsPanel v-if="activeTab === 'platforms'" />
      </div>

      <div v-if="!currentJob && activeTab === 'console'" class="empty">
        <p class="empty-title">还没有生成记录</p>
        <p class="empty-sub">先从机会工厂发车，系统会把日志、步骤和产物同步到这里。</p>
        <code class="empty-code">python apps/api/main.py</code>
      </div>
    </main>
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  background: linear-gradient(180deg, #fbfbfd 0%, #f5f5f7 42%, #f2f2f4 100%);
  transition: filter 0.2s;
}

.app--dimmed .main {
  filter: blur(2px) brightness(0.97);
  pointer-events: none;
}

.main {
  max-width: 1240px;
  margin: 0 auto;
  padding: calc(var(--nav-height) + 18px) 24px 64px;
}

.error-banner {
  background: rgba(255, 59, 48, 0.08);
  color: #c41e16;
  padding: 10px 16px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.retry-btn {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid rgba(196, 30, 22, 0.3);
  background: transparent;
  color: #c41e16;
  cursor: pointer;
}

.ws-banner {
  background: rgba(255, 149, 0, 0.08);
  color: #92400e;
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  margin-bottom: 12px;
}

.notice-banner {
  background: rgba(0, 113, 227, 0.08);
  color: #0060c0;
  padding: 10px 16px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-area {
  margin-top: 22px;
}

.empty {
  text-align: center;
  padding: 100px 20px;
}

.empty-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-1);
}

.empty-sub {
  font-size: 14px;
  color: var(--color-text-2);
  margin-top: 8px;
}

.empty-code {
  display: block;
  margin-top: 16px;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--color-text-2);
}
</style>
