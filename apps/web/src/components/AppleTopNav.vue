<script setup lang="ts">
import type { JobDetail, PipelineMode } from '../types/job'

const props = defineProps<{
  currentJob: JobDetail | null
  running: boolean
  mode: PipelineMode
}>()

const emit = defineEmits<{
  'toggle-menu': []
  start: []
  'update:mode': [value: PipelineMode]
}>()

function getAppName(): string {
  const c = props.currentJob?.artifacts?.['candidate.json']
  return c?.name_cn || c?.name || '机会工厂'
}

function startLabel(): string {
  if (props.running) return '运行中'
  if (props.mode === 'crawl') return '抓取机会'
  if (props.mode === 'queue') return '生产一条'
  return '一键生产'
}
</script>

<template>
  <nav class="nav">
    <div class="nav-inner">
      <div class="nav-left">
        <span class="brand-mark"></span>
        <span class="brand">Mini App Factory</span>
      </div>
      <div class="nav-center">
        <button class="app-name-btn" @click="emit('toggle-menu')">
          <span class="app-name-text">{{ getAppName() }}</span>
          <svg class="chevron" width="10" height="6" viewBox="0 0 10 6" fill="none">
            <path d="M1 1L5 5L9 1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
      <div class="nav-right">
        <div class="mode-toggle">
          <button
            class="mode-btn"
            :class="{ 'mode-btn--active': mode === 'auto' }"
            @click="emit('update:mode', 'auto')"
          >Auto</button>
          <button
            class="mode-btn"
            :class="{ 'mode-btn--active': mode === 'crawl' }"
            @click="emit('update:mode', 'crawl')"
          >Crawl</button>
          <button
            class="mode-btn"
            :class="{ 'mode-btn--active': mode === 'queue' }"
            @click="emit('update:mode', 'queue')"
          >Queue</button>
        </div>
        <span class="status-dot" :class="running ? 'status-dot--active' : 'status-dot--idle'"></span>
        <button class="start-btn" :disabled="running" @click="emit('start')">
          {{ startLabel() }}
        </button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: var(--nav-height);
  background: var(--color-surface);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--color-border);
  z-index: 1000;
}

.nav-inner {
  max-width: 1240px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.nav-left {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 9px;
}

.brand-mark {
  width: 18px;
  height: 18px;
  border-radius: 7px;
  background:
    radial-gradient(circle at 65% 25%, #fff 0 12%, transparent 13%),
    linear-gradient(145deg, #1d1d1f, #6e6e73);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.28), 0 5px 14px rgba(0,0,0,.12);
}

.brand {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-1);
  letter-spacing: -0.01em;
}

.nav-center {
  flex: 1;
  display: flex;
  justify-content: center;
}

.app-name-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  transition: background 0.15s;
}
.app-name-btn:hover {
  background: rgba(0, 0, 0, 0.04);
}

.app-name-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-1);
}

.chevron {
  color: var(--color-text-3);
}

.nav-right {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.mode-toggle {
  display: flex;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 980px;
  padding: 2px;
}

.mode-btn {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-2);
  background: none;
  border: none;
  border-radius: 980px;
  padding: 5px 10px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.mode-btn--active {
  background: #fff;
  color: var(--color-text-1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot--active {
  background: var(--color-green);
  box-shadow: 0 0 6px rgba(52, 199, 89, 0.4);
  animation: pulse 1.5s infinite;
}
.status-dot--idle {
  background: var(--color-text-3);
}

.start-btn {
  font-size: 13px;
  font-weight: 500;
  color: #fff;
  background: var(--color-blue);
  border: none;
  border-radius: 980px;
  padding: 7px 16px;
  cursor: pointer;
  transition: transform 0.15s var(--ease-apple), opacity 0.15s;
}
.start-btn:hover:not(:disabled) {
  transform: translateY(-1px);
}
.start-btn:active:not(:disabled) {
  transform: scale(0.98);
}
.start-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
