<script setup lang="ts">
import type {
  JobDetail,
  OpportunitySummary,
  OpportunityView,
  PipelineLaunchOptions,
  PipelineMode,
} from '../types/job'

type LaunchPreset = {
  id: string
  label: string
  blurb: string
  options: PipelineLaunchOptions
}

const props = defineProps<{
  summary: OpportunitySummary | null
  currentJob: JobDetail | null
  running: boolean
  mode: PipelineMode
  launchOptions: PipelineLaunchOptions
}>()

const emit = defineEmits<{
  start: [mode: PipelineMode]
  stop: []
  refresh: []
  'open-view': [view: OpportunityView]
  'update-launch-options': [next: PipelineLaunchOptions]
  'queue-action': [payload: { action: 'prioritize' | 'skip' | 'retry' | 'generate_now'; queueId: string }]
  'reset-processed': []
}>()

function confirmResetProcessed() {
  // 破坏性操作：清空已生产记录会让历史 app 重新进入候选、可能重复生产，必须二次确认。
  const ok = window.confirm(
    '确定重置「已生产记录」吗？\n\n已生产过的 app 会重新进入候选列表，可能被再次生产。后端会在重置前自动备份。',
  )
  if (ok) emit('reset-processed')
}

function runQueueAction(action: 'prioritize' | 'skip' | 'retry' | 'generate_now', item: any) {
  const queueId = item?.queue_id
  if (!queueId) return
  emit('queue-action', { action, queueId })
}

const presets: LaunchPreset[] = [
  {
    id: 'cn',
    label: 'China',
    blurb: '先锁中国区热点，最快出第一批可做机会。',
    options: { regions: 'CN', platforms: 'app_store', limit: 12, max_generate: 1 },
  },
  {
    id: 'asia',
    label: 'Asia',
    blurb: '覆盖中日港新，适合找轻传播和内容工具题材。',
    options: { regions: 'CN,JP,HK,SG', platforms: 'app_store,google_play', limit: 18, max_generate: 2 },
  },
  {
    id: 'global',
    label: 'Global',
    blurb: '看跨地区重复出现的高热需求，再批量转成模板机会。',
    options: { regions: 'CN,US,JP,BR', platforms: 'app_store,google_play', limit: 24, max_generate: 3 },
  },
]

const regionChoices = [
  { id: 'CN', label: 'CN' },
  { id: 'CN,US', label: 'CN + US' },
  { id: 'CN,US,JP', label: 'CN + US + JP' },
  { id: 'CN,JP,HK,SG', label: 'Asia Mix' },
]

const platformChoices = [
  { id: 'app_store', label: 'App Store' },
  { id: 'google_play', label: 'Google Play' },
  { id: 'app_store,google_play', label: 'Dual Source' },
]

// 数字输入框校验：空/非法值回退到 fallback，否则取整并夹在 [min, max]。
function clampInt(raw: string, min: number, max: number, fallback: number): number {
  const v = Math.floor(Number(raw))
  if (!Number.isFinite(v)) return fallback
  return Math.min(Math.max(v, min), max)
}

function n(v: any, fallback = '0') {
  if (v === undefined || v === null || v === '') return fallback
  return Number(v).toLocaleString()
}

function pct(v: any) {
  if (v === undefined || v === null || Number.isNaN(Number(v))) return '--'
  return Math.round(Number(v)).toString()
}

function updatedText() {
  const raw = props.summary?.updated_at
  if (!raw) return '等待首次抓取'
  try {
    return new Date(raw).toLocaleString()
  } catch {
    return raw
  }
}

function topQueue() {
  return props.summary?.top_queue || []
}

function topCandidates() {
  return props.summary?.top_candidates || []
}

function topFeatures() {
  return props.summary?.top_features || []
}

function templateEntries() {
  const data = props.summary?.top_templates || {}
  return Object.entries(data).slice(0, 5)
}

function templateShare(count: unknown) {
  const total = Object.values(props.summary?.top_templates || {}).reduce((sum, value) => sum + Number(value || 0), 0)
  if (!total) return '0%'
  return `${Math.round((Number(count || 0) / total) * 100)}%`
}

function latestJobName() {
  const c = props.currentJob?.artifacts?.['candidate.json']
  return c?.name_cn || c?.name || props.currentJob?.id || '暂无生成记录'
}

function qaState() {
  const qa = props.currentJob?.artifacts?.['qa-report.json']
  if (!qa) return '等待生成'
  return qa.passed ? 'QA 通过' : 'QA 待修复'
}

// 当前 job 的传播闭环状态：读 growth-qa 的实际检查项，而不是只看文件是否存在。
function viralLoopState() {
  const g = props.currentJob?.artifacts?.['growth-qa-report.json']
  const c = g?.checks
  if (!c) return '传播闭环：等待生成'
  const share = c.result_has_share_cta
  const unlock = c.result_has_unlock_hook
  const watermark = c.result_has_watermark
  const api = c.generation_api_contract
  const parts = [
    `分享${share ? '✓' : '✗'}`,
    `解锁${unlock ? '✓' : '✗'}`,
    `水印${watermark ? '✓' : '✗'}`,
    `真实API${api ? '✓' : '✗'}`,
  ]
  return `传播闭环：${parts.join(' · ')}`
}

function queueHealthText() {
  const pending = Number(props.summary?.queue_stats?.pending || 0)
  if (pending >= 12) return '机会池充足，适合连续生成。'
  if (pending >= 4) return '队列健康，可以继续验证模板产能。'
  if (pending > 0) return '队列偏薄，建议继续抓取补充。'
  return '先抓取机会，系统才会排出下一批小程序。'
}

function launchSummary() {
  return `${props.launchOptions.regions} · ${props.launchOptions.platforms} · limit ${props.launchOptions.limit} · generate ${props.launchOptions.max_generate}`
}

function updateOptions(patch: Partial<PipelineLaunchOptions>) {
  emit('update-launch-options', { ...props.launchOptions, ...patch })
}

function applyPreset(preset: LaunchPreset) {
  emit('update-launch-options', preset.options)
}

function isPresetActive(preset: LaunchPreset) {
  return (
    preset.options.regions === props.launchOptions.regions &&
    preset.options.platforms === props.launchOptions.platforms &&
    preset.options.limit === props.launchOptions.limit &&
    preset.options.max_generate === props.launchOptions.max_generate
  )
}

function openView(view: OpportunityView) {
  emit('open-view', view)
}
</script>

<template>
  <section class="hero">
    <div class="eyebrow">Opportunity Factory</div>
    <h1>先抓机会，再批量生产。</h1>
    <p class="hero-copy">
      不是先做一个功能，而是先从 App Store / Google Play 里找出值得复制、适合传播、
      还能落到模板的小程序机会，再自动排队生成。
    </p>
    <div class="hero-actions">
      <button class="primary" :disabled="running" @click="emit('start', 'auto')">一键抓取并生产</button>
      <button class="secondary" :disabled="running" @click="emit('start', 'crawl')">只抓取机会</button>
      <button class="secondary" :disabled="running" @click="emit('start', 'queue')">消费队列</button>
      <button class="ghost" @click="emit('refresh')">刷新数据</button>
      <button
        class="chip force-refresh-chip"
        type="button"
        :class="{ 'chip--active': launchOptions.force_refresh }"
        :aria-pressed="launchOptions.force_refresh ? 'true' : 'false'"
        data-testid="force-refresh-toggle"
        title="忽略已生产去重，强制重新抓取/生产已处理过的 app"
        @click="updateOptions({ force_refresh: !launchOptions.force_refresh })"
      >
        强制刷新
      </button>
      <button
        class="ghost danger-ghost"
        type="button"
        data-testid="reset-processed-btn"
        title="重置已生产记录，让历史 app 重新进入候选（破坏性，后端自动备份）"
        @click="confirmResetProcessed"
      >
        重置已生产记录
      </button>
    </div>
    <div class="hero-stop">
      <button class="stop-btn" :disabled="!running" @click="emit('stop')">STOP</button>
    </div>
  </section>

  <section class="launch-deck">
    <div class="deck-story">
      <span class="section-label">Launch Deck</span>
      <h2>让抓取范围和生产节奏都变得可控。</h2>
      <p>
        这块不是传统后台的表单，而是机会工厂的发车面板：先决定抓哪些地区、看几个机会、一次生成几个候选。
      </p>
      <div class="deck-summary">
        <span>当前计划</span>
        <strong>{{ launchSummary() }}</strong>
      </div>
    </div>

    <div class="deck-controls">
      <div class="control-block">
        <span class="control-label">Presets</span>
        <div class="preset-grid">
          <button
            v-for="preset in presets"
            :key="preset.id"
            :data-testid="`preset-${preset.id}`"
            class="preset-card"
            :class="{ 'preset-card--active': isPresetActive(preset) }"
            @click="applyPreset(preset)"
          >
            <strong>{{ preset.label }}</strong>
            <span>{{ preset.blurb }}</span>
          </button>
        </div>
      </div>

      <div class="control-block">
        <span class="control-label">Regions</span>
        <div class="chip-row">
          <button
            v-for="choice in regionChoices"
            :key="choice.id"
            class="chip"
            :class="{ 'chip--active': launchOptions.regions === choice.id }"
            @click="updateOptions({ regions: choice.id })"
          >
            {{ choice.label }}
          </button>
        </div>
      </div>

      <div class="control-inline">
        <div class="control-block">
          <span class="control-label">Sources</span>
          <div class="chip-row">
            <button
              v-for="choice in platformChoices"
              :key="choice.id"
              class="chip"
              :class="{ 'chip--active': launchOptions.platforms === choice.id }"
              @click="updateOptions({ platforms: choice.id })"
            >
              {{ choice.label }}
            </button>
          </div>
        </div>

        <div class="control-block">
          <span class="control-label">Limit</span>
          <div class="num-field">
            <input
              class="num-input"
              type="number"
              min="1"
              :value="launchOptions.limit"
              @input="updateOptions({ limit: clampInt(($event.target as HTMLInputElement).value, 1, 500, 50) })"
            />
            <div class="num-stepper">
              <button type="button" class="num-step" @click="updateOptions({ limit: clampInt(String(launchOptions.limit + 1), 1, 500, 50) })">▲</button>
              <button type="button" class="num-step" @click="updateOptions({ limit: clampInt(String(launchOptions.limit - 1), 1, 500, 50) })">▼</button>
            </div>
          </div>
        </div>

        <div class="control-block">
          <span class="control-label">Generate</span>
          <div class="num-field">
            <input
              class="num-input"
              type="number"
              min="1"
              :value="launchOptions.max_generate"
              @input="updateOptions({ max_generate: clampInt(($event.target as HTMLInputElement).value, 1, 50, 5) })"
            />
            <div class="num-stepper">
              <button type="button" class="num-step" @click="updateOptions({ max_generate: clampInt(String(launchOptions.max_generate + 1), 1, 50, 5) })">▲</button>
              <button type="button" class="num-step" @click="updateOptions({ max_generate: clampInt(String(launchOptions.max_generate - 1), 1, 50, 5) })">▼</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <section class="lineup">
    <article class="line-card line-card--dark" data-testid="crawl-card">
      <span class="line-kicker">Crawl</span>
      <strong>{{ n(summary?.crawl_stats?.fetched_tasks) }}</strong>
      <p>成功抓取任务</p>
    </article>
    <article class="line-card line-card--interactive" data-testid="candidates-card" @click="openView('candidates')">
      <span class="line-kicker">Candidates</span>
      <strong>{{ n(summary?.dedup_stats?.unique_apps) }}</strong>
      <p>去重后的候选 App</p>
    </article>
    <article class="line-card line-card--interactive" data-testid="features-card" @click="openView('features')">
      <span class="line-kicker">Features</span>
      <strong>{{ n(summary?.feature_stats?.recommended_features) }}</strong>
      <p>可生产功能机会</p>
    </article>
    <article class="line-card line-card--blue line-card--interactive" data-testid="queue-card" @click="openView('queue')">
      <span class="line-kicker">Queue</span>
      <strong>{{ n(summary?.queue_stats?.pending) }}</strong>
      <p>等待生成的小程序</p>
    </article>
  </section>

  <section class="story-grid">
    <article class="story-card story-card--large">
      <div>
        <span class="section-label">Production Queue</span>
        <h2>下一批要生产什么，已经排好。</h2>
      </div>
      <div v-if="topQueue().length" class="queue-list">
        <div
          v-for="item in topQueue()"
          :key="item.queue_id"
          class="queue-item"
        >
          <button class="queue-item-main" @click="openView('queue')">
            <div>
              <strong>{{ item.feature_name_cn || item.feature_key }}</strong>
              <span>{{ item.parent_app_name || '来源 App' }} · {{ item.selected_template || 'template' }}</span>
            </div>
            <em>{{ pct(item.final_score) }}</em>
          </button>
          <div class="queue-item-actions">
            <button
              class="qa-btn"
              :disabled="running || item.status === 'queued'"
              @click.stop="runQueueAction('generate_now', item)"
            >{{ item.status === 'queued' ? '任务进行中' : '创建生成任务' }}</button>
            <button class="qa-btn ghost" @click.stop="runQueueAction('prioritize', item)">提权</button>
            <button class="qa-btn ghost" @click.stop="runQueueAction('retry', item)">重试</button>
            <button class="qa-btn ghost" @click.stop="runQueueAction('skip', item)">跳过</button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <strong>还没有机会队列</strong>
        <span>先运行 Crawl，系统会把抓到的 App 拆成功能机会。</span>
      </div>
    </article>

    <article class="story-card">
      <span class="section-label">Templates</span>
      <h2>模板分布</h2>
      <div class="template-list">
        <div v-for="[name, count] in templateEntries()" :key="name" class="template-row">
          <div>
            <span>{{ name }}</span>
            <small>{{ templateShare(count) }}</small>
          </div>
          <strong>{{ count }}</strong>
        </div>
        <div v-if="!templateEntries().length" class="muted">等待抓取后生成模板分布</div>
      </div>
    </article>

    <article class="story-card story-card--signal">
      <span class="section-label">Factory Signal</span>
      <h2>{{ latestJobName() }}</h2>
      <p class="build-copy">{{ qaState() }} · {{ currentJob?.id || '暂无 job' }}</p>
      <div class="signal-copy">{{ viralLoopState() }}</div>
      <div class="signal-copy">{{ queueHealthText() }}</div>
      <div class="build-chip">{{ mode.toUpperCase() }}</div>
    </article>
  </section>

  <section class="system-strip">
    <div>
      <span>数据更新时间</span>
      <strong>{{ updatedText() }}</strong>
    </div>
    <div>
      <span>当前模式</span>
      <strong>{{ mode }}</strong>
    </div>
    <div>
      <span>运行状态</span>
      <strong>{{ running ? '正在生产' : '待命' }}</strong>
    </div>
  </section>

  <section class="explore-grid">
    <article class="explore-card explore-card--interactive" @click="openView('candidates')">
      <div class="explore-head">
        <span class="section-label">Candidates</span>
        <h2>市场里最强的候选 App</h2>
      </div>
      <div v-if="topCandidates().length" class="explore-list">
        <div v-for="item in topCandidates()" :key="item.canonical_key" class="explore-row">
          <div>
            <strong>{{ item.name_cn || item.name }}</strong>
            <span>{{ (item.regions || []).join(', ') || 'region n/a' }} · {{ item.appear_count || 0 }} 次出现</span>
          </div>
          <em>#{{ item.best_rank || '--' }}</em>
        </div>
      </div>
      <div v-else class="muted">还没有候选池数据</div>
    </article>

    <article class="explore-card explore-card--interactive" @click="openView('features')">
      <div class="explore-head">
        <span class="section-label">Features</span>
        <h2>拆出来的可生产功能</h2>
      </div>
      <div v-if="topFeatures().length" class="explore-list">
        <div v-for="item in topFeatures()" :key="item.feature_key" class="explore-row">
          <div>
            <strong>{{ item.feature_name_cn || item.feature_name }}</strong>
            <span>{{ item.parent_app_name || '来源 App' }} · {{ item.selected_template || 'template' }}</span>
          </div>
          <em>{{ pct(item.miniapp_fit_score || item.final_score) }}</em>
        </div>
      </div>
      <div v-else class="muted">还没有 feature opportunities</div>
    </article>
  </section>
</template>

<style scoped>
.hero {
  min-height: 520px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 92px 24px 74px;
  border-radius: 34px;
  background:
    radial-gradient(circle at 50% 18%, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.52) 34%, transparent 66%),
    linear-gradient(180deg, #fbfbfd 0%, #f5f5f7 52%, #ececf1 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
  overflow: hidden;
  position: relative;
}

.hero::after {
  content: "";
  position: absolute;
  width: 620px;
  height: 210px;
  bottom: -96px;
  border-radius: 50%;
  background: radial-gradient(ellipse, rgba(0, 113, 227, 0.18), transparent 68%);
  filter: blur(4px);
}

.eyebrow {
  position: relative;
  z-index: 1;
  color: #0071e3;
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 14px;
}

h1 {
  position: relative;
  z-index: 1;
  max-width: 900px;
  font-size: clamp(44px, 7vw, 86px);
  line-height: 0.96;
  letter-spacing: -0.065em;
  color: #1d1d1f;
}

.hero-copy {
  position: relative;
  z-index: 1;
  max-width: 760px;
  margin-top: 24px;
  color: #6e6e73;
  font-size: clamp(18px, 2vw, 24px);
  line-height: 1.35;
  letter-spacing: -0.025em;
}

.hero-actions {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  margin-top: 34px;
}

.hero-stop {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

.stop-btn {
  border-radius: 999px;
  padding: 12px 32px;
  background: #ff3b30;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 1px;
  border: none;
  cursor: pointer;
  transition: background 0.18s, transform 0.18s var(--ease-apple);
}

.stop-btn:hover:not(:disabled) {
  background: #e0241b;
  transform: translateY(-1px);
}

.stop-btn:disabled {
  background: #f0d2d0;
  color: #fff;
  cursor: not-allowed;
}

.primary,
.secondary,
.ghost {
  border-radius: 999px;
  padding: 12px 21px;
  font-size: 15px;
  font-weight: 600;
  transition: transform 0.18s var(--ease-apple), opacity 0.18s, box-shadow 0.18s;
}

.primary {
  background: #0071e3;
  color: #fff;
  box-shadow: 0 10px 24px rgba(0, 113, 227, 0.24);
}

.secondary {
  background: #fff;
  color: #0071e3;
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.2);
}

.ghost {
  background: transparent;
  color: #1d1d1f;
}

.primary:hover:not(:disabled),
.secondary:hover:not(:disabled),
.ghost:hover:not(:disabled) {
  transform: translateY(-2px);
}

button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.launch-deck {
  margin-top: 18px;
  display: grid;
  grid-template-columns: 0.9fr 1.1fr;
  gap: 18px;
}

.deck-story,
.deck-controls {
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.88);
  padding: 28px;
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(14px);
}

.section-label {
  color: #6e6e73;
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.deck-story h2,
.story-card h2,
.explore-head h2 {
  margin-top: 8px;
  font-size: clamp(28px, 4vw, 44px);
  line-height: 1.02;
  letter-spacing: -0.045em;
}

.deck-story p {
  margin-top: 16px;
  color: #6e6e73;
  font-size: 15px;
  line-height: 1.55;
}

.deck-summary {
  margin-top: 26px;
  padding: 18px 20px;
  border-radius: 22px;
  background: linear-gradient(135deg, #101113, #2e3137);
  color: #fff;
}

.deck-summary span,
.deck-summary strong {
  display: block;
}

.deck-summary span {
  font-size: 12px;
  opacity: 0.7;
}

.deck-summary strong {
  margin-top: 8px;
  font-size: 19px;
  line-height: 1.25;
  letter-spacing: -0.03em;
}

.deck-controls {
  display: grid;
  gap: 18px;
}

.control-block {
  display: grid;
  gap: 2px;
  align-content: start;
}

.control-inline {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}

.control-label {
  color: #6e6e73;
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.preset-card {
  display: grid;
  gap: 8px;
  min-height: 118px;
  padding: 16px;
  border-radius: 24px;
  background: linear-gradient(180deg, #fbfbfd 0%, #f4f4f6 100%);
  text-align: left;
  transition: transform 0.18s var(--ease-apple), box-shadow 0.18s, border-color 0.18s;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.04);
}

.preset-card strong {
  font-size: 18px;
  color: #1d1d1f;
}

.preset-card span {
  color: #6e6e73;
  font-size: 12px;
  line-height: 1.45;
}

.preset-card:hover,
.chip:hover,
.line-card--interactive:hover,
.explore-card--interactive:hover {
  transform: translateY(-2px);
}

.preset-card--active {
  background: linear-gradient(180deg, rgba(0, 113, 227, 0.12) 0%, rgba(255, 255, 255, 0.96) 100%);
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.16), 0 18px 34px rgba(0, 113, 227, 0.08);
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.chip {
  border-radius: 999px;
  padding: 9px 14px;
  background: #f5f5f7;
  color: #6e6e73;
  font-size: 12px;
  font-weight: 600;
  transition: background 0.18s, color 0.18s, transform 0.18s var(--ease-apple);
}

.chip--numeric {
  min-width: 52px;
}

.num-field {
  display: flex;
  align-items: center;
  gap: 2px;
}

.num-input {
  width: 64px;
  padding: 2px 4px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #1d1d1f;
  font-size: 30px;
  font-weight: 700;
  text-align: left;
  outline: none;
  -moz-appearance: textfield;
  appearance: textfield;
}

/* 隐藏原生数字调节箭头，改用右侧自定义步进器 */
.num-input::-webkit-outer-spin-button,
.num-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.num-input:focus {
  background: #f5f5f7;
}

.num-stepper {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.num-step {
  border: none;
  background: #f0f0f3;
  color: #6e6e73;
  width: 22px;
  height: 16px;
  border-radius: 5px;
  font-size: 9px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.num-step:hover {
  background: #1d1d1f;
  color: #fff;
}

.chip--active {
  background: #1d1d1f;
  color: #fff;
}

.lineup {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-top: 22px;
}

.line-card {
  min-height: 190px;
  border-radius: 28px;
  background: #fff;
  padding: 24px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.line-card--interactive,
.queue-item,
.explore-card--interactive {
  cursor: pointer;
}

.line-card--dark {
  background: #1d1d1f;
  color: #fff;
}

.line-card--blue {
  background: linear-gradient(145deg, #0071e3, #4db2ff);
  color: #fff;
}

.line-kicker {
  color: inherit;
  opacity: 0.68;
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.line-card strong {
  font-size: clamp(42px, 6vw, 64px);
  line-height: 0.9;
  letter-spacing: -0.055em;
}

.line-card p {
  color: inherit;
  opacity: 0.72;
  font-size: 15px;
}

.story-grid {
  display: grid;
  grid-template-columns: 1.25fr 0.75fr;
  gap: 18px;
  margin-top: 18px;
}

.story-card {
  min-height: 280px;
  border-radius: 30px;
  background: #fff;
  padding: 28px;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.story-card--large {
  grid-row: span 2;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.story-card--signal {
  background:
    radial-gradient(circle at 78% 18%, rgba(0, 113, 227, 0.12), transparent 32%),
    linear-gradient(180deg, #ffffff 0%, #f5f8ff 100%);
}

.queue-list {
  margin-top: 30px;
  display: grid;
  gap: 10px;
}

.queue-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 15px 16px;
  border-radius: 18px;
  background: #f5f5f7;
  text-align: left;
}

.queue-item strong,
.queue-item span {
  display: block;
}

.queue-item strong {
  font-size: 15px;
}

.queue-item span {
  margin-top: 4px;
  color: #6e6e73;
  font-size: 12px;
}

.queue-item em {
  min-width: 50px;
  text-align: center;
  color: #0071e3;
  font-size: 24px;
  font-style: normal;
  font-weight: 700;
}

.template-list {
  margin-top: 26px;
  display: grid;
  gap: 12px;
}

.template-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.template-row div {
  display: grid;
  gap: 3px;
}

.template-row small,
.template-row span,
.muted,
.build-copy,
.empty-state span,
.signal-copy {
  color: #6e6e73;
}

.signal-copy {
  margin-top: 18px;
  line-height: 1.55;
}

.build-chip {
  display: inline-flex;
  margin-top: 28px;
  border-radius: 999px;
  background: #f5f5f7;
  padding: 8px 12px;
  color: #0071e3;
  font-size: 12px;
  font-weight: 700;
}

.empty-state {
  margin-top: 34px;
  padding: 24px;
  border-radius: 22px;
  background: #f5f5f7;
}

.empty-state strong,
.empty-state span {
  display: block;
}

.empty-state span {
  margin-top: 6px;
}

.system-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  margin: 18px 0 4px;
  overflow: hidden;
  border-radius: 24px;
  background: rgba(0, 0, 0, 0.08);
}

.system-strip div {
  background: rgba(255, 255, 255, 0.82);
  padding: 20px 24px;
}

.system-strip span,
.system-strip strong {
  display: block;
}

.system-strip span {
  color: #6e6e73;
  font-size: 12px;
}

.system-strip strong {
  margin-top: 4px;
  font-size: 15px;
}

.explore-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 18px;
}

.explore-card {
  border-radius: 28px;
  background: #fff;
  padding: 28px;
  box-shadow: var(--shadow-card);
  transition: transform 0.18s var(--ease-apple);
}

.explore-head h2 {
  font-size: clamp(24px, 3vw, 34px);
  line-height: 1.08;
  letter-spacing: -0.04em;
}

.explore-list {
  margin-top: 22px;
  display: grid;
  gap: 12px;
}

.explore-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.explore-row:last-child {
  border-bottom: 0;
}

.explore-row strong,
.explore-row span {
  display: block;
}

.explore-row strong {
  font-size: 15px;
}

.explore-row span {
  margin-top: 4px;
  color: #6e6e73;
  font-size: 12px;
}

.explore-row em {
  min-width: 56px;
  text-align: right;
  color: #1d1d1f;
  font-style: normal;
  font-size: 18px;
  font-weight: 600;
}

@media (max-width: 1024px) {
  .launch-deck,
  .story-grid,
  .explore-grid,
  .control-inline {
    grid-template-columns: 1fr;
  }

  .preset-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .hero {
    min-height: 460px;
    border-radius: 26px;
    padding: 76px 18px 56px;
  }

  .lineup,
  .system-strip {
    grid-template-columns: 1fr;
  }

  .story-card--large {
    grid-row: auto;
  }
}
</style>
