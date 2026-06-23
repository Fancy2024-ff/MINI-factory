<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { OpportunityView } from '../types/job'

const props = defineProps<{
  queue: any[]
  candidates: any[]
  features: any[]
  selectedView: OpportunityView
}>()

const emit = defineEmits<{
  'update:selectedView': [value: OpportunityView]
}>()

const tabs = [
  { id: 'queue', label: '生产队列' },
  { id: 'candidates', label: '候选 App' },
  { id: 'features', label: '功能机会' },
] as const

const activeFilter = ref('all')

watch(() => props.selectedView, () => {
  activeFilter.value = 'all'
})

const list = computed(() => {
  if (props.selectedView === 'candidates') return props.candidates
  if (props.selectedView === 'features') return props.features
  return props.queue
})

const filterOptions = computed(() => {
  const map = new Map<string, number>()
  for (const item of list.value) {
    let key = ''
    if (props.selectedView === 'candidates') {
      key = (item.regions || [])[0] || 'unknown'
    } else if (props.selectedView === 'features') {
      key = item.selected_template || 'template'
    } else {
      key = item.selected_template || item.status || 'pending'
    }
    map.set(key, (map.get(key) || 0) + 1)
  }
  return [{ id: 'all', label: '全部', count: list.value.length }].concat(
    Array.from(map.entries()).slice(0, 6).map(([id, count]) => ({ id, label: id, count }))
  )
})

const filteredList = computed(() => {
  if (activeFilter.value === 'all') return list.value
  return list.value.filter((item) => {
    if (props.selectedView === 'candidates') {
      return (item.regions || []).includes(activeFilter.value)
    }
    return (item.selected_template || item.status || 'pending') === activeFilter.value
  })
})

const featuredItem = computed(() => filteredList.value[0] || null)
const remainingItems = computed(() => filteredList.value.slice(featuredItem.value ? 1 : 0))

function titleFor(item: any) {
  if (props.selectedView === 'queue') return item.feature_name_cn || item.feature_key || 'Untitled'
  if (props.selectedView === 'candidates') return item.name_cn || item.name || item.canonical_key || 'Candidate'
  return item.feature_name_cn || item.feature_name || item.feature_key || 'Feature'
}

function subtitleFor(item: any) {
  if (props.selectedView === 'queue') {
    return `${item.parent_app_name || '来源 App'} · ${item.selected_template || 'template'}`
  }
  if (props.selectedView === 'candidates') {
    const regions = (item.regions || []).slice(0, 4).join(', ') || 'region n/a'
    return `${regions} · ${item.appear_count || 0} 次出现`
  }
  return `${item.parent_app_name || '来源 App'} · ${item.selected_template || 'template'}`
}

function metricFor(item: any) {
  if (props.selectedView === 'queue') return item.final_score ?? '--'
  if (props.selectedView === 'candidates') return item.best_rank ? `#${item.best_rank}` : '--'
  return item.miniapp_fit_score ?? item.final_score ?? '--'
}

function metricLabel() {
  if (props.selectedView === 'queue') return 'Priority'
  if (props.selectedView === 'candidates') return 'Best Rank'
  return 'Miniapp Fit'
}

function badgeFor(item: any) {
  if (props.selectedView === 'queue') return item.status || 'pending'
  if (props.selectedView === 'candidates') return item.rating_available ? 'rated' : 'ranking'
  return item.production_recommended === false ? 'unsupported' : 'recommended'
}

function metaFor(item: any) {
  if (props.selectedView === 'queue') {
    return item.reason?.[0] || '等待被消费进代码生成主链路。'
  }
  if (props.selectedView === 'candidates') {
    return (item.categories || []).slice(0, 3).join(' · ') || '未标类目'
  }
  return item.required_capabilities?.join(' · ') || '规则拆解机会'
}

function chipsFor(item: any) {
  if (props.selectedView === 'candidates') {
    return (item.regions || []).slice(0, 4)
  }
  if (props.selectedView === 'features') {
    return (item.required_capabilities || []).slice(0, 3)
  }
  return [item.selected_template, item.status].filter(Boolean).slice(0, 3)
}

function eyebrow() {
  if (props.selectedView === 'queue') return 'Production Queue'
  if (props.selectedView === 'candidates') return 'Candidate Pool'
  return 'Feature Opportunities'
}

function heading() {
  if (props.selectedView === 'queue') return '优先消费哪一条，应该很清楚。'
  if (props.selectedView === 'candidates') return '哪些 App 在不同地区重复出现，直接看得见。'
  return '哪些功能最适合拆成小程序，也能一眼看出来。'
}
</script>

<template>
  <section class="explorer">
    <div class="explorer-head">
      <div>
        <span class="eyebrow">Opportunity Data</span>
        <h2>把抓到的数据，直接变成决策界面。</h2>
      </div>
      <div class="switcher">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          :data-testid="`tab-${tab.id}`"
          class="switch-btn"
          :class="{ 'switch-btn--active': selectedView === tab.id }"
          @click="emit('update:selectedView', tab.id)"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <div class="filter-row">
      <button
        v-for="option in filterOptions"
        :key="option.id"
        class="filter-chip"
        :class="{ 'filter-chip--active': activeFilter === option.id }"
        @click="activeFilter = option.id"
      >
        <span>{{ option.label }}</span>
        <strong>{{ option.count }}</strong>
      </button>
    </div>

    <div v-if="featuredItem" class="hero-card">
      <div class="hero-copy">
        <span class="section-label">{{ eyebrow() }}</span>
        <h3>{{ heading() }}</h3>
        <strong class="hero-title">{{ titleFor(featuredItem) }}</strong>
        <p class="subtitle">{{ subtitleFor(featuredItem) }}</p>
        <p class="meta">{{ metaFor(featuredItem) }}</p>
        <div class="pill-row">
          <span v-for="chip in chipsFor(featuredItem)" :key="chip" class="pill">{{ chip }}</span>
        </div>
      </div>
      <div class="hero-metric">
        <span>{{ metricLabel() }}</span>
        <strong>{{ metricFor(featuredItem) }}</strong>
        <em>{{ badgeFor(featuredItem) }}</em>
      </div>
    </div>

    <div v-if="remainingItems.length" class="data-grid">
      <article
        v-for="item in remainingItems"
        :key="item.queue_id || item.canonical_key || item.feature_key"
        class="data-card"
      >
        <div class="card-top">
          <strong>{{ titleFor(item) }}</strong>
          <span class="badge">{{ badgeFor(item) }}</span>
        </div>
        <p class="subtitle">{{ subtitleFor(item) }}</p>
        <div class="metric">{{ metricFor(item) }}</div>
        <div class="meta">{{ metaFor(item) }}</div>
        <div class="pill-row">
          <span v-for="chip in chipsFor(item)" :key="chip" class="pill">{{ chip }}</span>
        </div>
      </article>
    </div>

    <div v-else-if="!featuredItem" class="empty">
      <strong>还没有机会数据</strong>
      <span>先运行抓取，系统会把候选 App、feature 和生产队列同步到这里。</span>
    </div>
  </section>
</template>

<style scoped>
.explorer {
  margin-top: 18px;
  padding: 30px;
  border-radius: 30px;
  background: #ffffff;
  box-shadow: var(--shadow-card);
}

.explorer-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
}

.eyebrow,
.section-label {
  color: #6e6e73;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.explorer h2 {
  margin-top: 8px;
  font-size: clamp(26px, 3vw, 40px);
  line-height: 1.04;
  letter-spacing: -0.045em;
}

.switcher {
  display: inline-flex;
  padding: 4px;
  border-radius: 999px;
  background: #f5f5f7;
}

.switch-btn {
  border-radius: 999px;
  padding: 9px 14px;
  background: transparent;
  color: #6e6e73;
  font-size: 12px;
  font-weight: 600;
}

.switch-btn--active {
  background: #ffffff;
  color: #1d1d1f;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 999px;
  background: #f5f5f7;
  color: #6e6e73;
  transition: transform 0.18s var(--ease-apple), background 0.18s, color 0.18s;
}

.filter-chip strong {
  color: #1d1d1f;
}

.filter-chip:hover {
  transform: translateY(-1px);
}

.filter-chip--active {
  background: #1d1d1f;
  color: #fff;
}

.filter-chip--active strong {
  color: #fff;
}

.hero-card {
  margin-top: 22px;
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 16px;
  padding: 24px;
  border-radius: 28px;
  background:
    radial-gradient(circle at 82% 20%, rgba(0, 113, 227, 0.1), transparent 32%),
    linear-gradient(180deg, #fbfbfd 0%, #f4f7fb 100%);
}

.hero-copy h3 {
  margin-top: 8px;
  font-size: clamp(26px, 3vw, 38px);
  line-height: 1.08;
  letter-spacing: -0.04em;
}

.hero-title {
  display: block;
  margin-top: 20px;
  font-size: 22px;
  line-height: 1.08;
  letter-spacing: -0.03em;
}

.subtitle {
  margin-top: 8px;
  color: #6e6e73;
  font-size: 13px;
  line-height: 1.45;
}

.meta {
  margin-top: 10px;
  color: #6e6e73;
  font-size: 12px;
  line-height: 1.5;
}

.hero-metric {
  display: grid;
  align-content: end;
  justify-items: end;
  text-align: right;
}

.hero-metric span {
  color: #6e6e73;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.hero-metric strong {
  margin-top: 8px;
  font-size: clamp(52px, 7vw, 84px);
  line-height: 0.92;
  letter-spacing: -0.065em;
}

.hero-metric em {
  margin-top: 12px;
  display: inline-flex;
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
  font-style: normal;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.data-grid {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.data-card {
  padding: 18px;
  border-radius: 22px;
  background: linear-gradient(180deg, #fbfbfd 0%, #f4f4f6 100%);
  min-height: 200px;
  display: flex;
  flex-direction: column;
}

.card-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.card-top strong {
  font-size: 16px;
  line-height: 1.18;
}

.badge {
  flex-shrink: 0;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #0071e3;
  background: rgba(0, 113, 227, 0.08);
  text-transform: uppercase;
}

.metric {
  margin-top: auto;
  padding-top: 20px;
  font-size: 34px;
  font-weight: 700;
  letter-spacing: -0.05em;
  line-height: 0.95;
}

.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.pill {
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.04);
  color: #6e6e73;
  font-size: 11px;
  font-weight: 600;
}

.empty {
  margin-top: 22px;
  padding: 26px;
  border-radius: 22px;
  background: #f5f5f7;
}

.empty strong,
.empty span {
  display: block;
}

.empty span {
  margin-top: 6px;
  color: #6e6e73;
}

@media (max-width: 980px) {
  .explorer-head,
  .hero-card {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: flex-start;
  }

  .explorer-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .hero-metric {
    justify-items: flex-start;
    text-align: left;
  }

  .data-grid {
    grid-template-columns: 1fr;
  }
}
</style>
