<!-- /tg/avatar：AI 头像 / 写真风格图生成（文字生成，非图生图换脸）。移动端优先。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">AI 头像生成</div>
      <div class="top-spacer"></div>
    </header>

    <section class="form" v-if="phase !== 'result'">
      <p class="hint">用文字描述生成社交头像 / 写真风格图（暂不支持上传自拍）</p>

      <label class="field-label">人物描述</label>
      <textarea
        class="prompt-input"
        v-model="prompt"
        :maxlength="MAX_PROMPT_LEN"
        placeholder="例如：25 岁短发女生，简约时尚，自信微笑"
        rows="3"
      ></textarea>
      <div class="counter">{{ prompt.length }}/{{ MAX_PROMPT_LEN }}</div>

      <label class="field-label">风格</label>
      <div class="chips">
        <button v-for="s in styles" :key="s.id" class="chip" :class="{ active: style === s.id }" @click="style = style === s.id ? '' : s.id">{{ s.label }}</button>
      </div>

      <label class="field-label">气质</label>
      <div class="chips">
        <button v-for="m in moods" :key="m.id" class="chip" :class="{ active: mood === m.id }" @click="mood = mood === m.id ? '' : m.id">{{ m.label }}</button>
      </div>

      <label class="field-label">场景</label>
      <div class="chips">
        <button v-for="sc in scenes" :key="sc.id" class="chip" :class="{ active: scene === sc.id }" @click="scene = scene === sc.id ? '' : sc.id">{{ sc.label }}</button>
      </div>

      <button class="generate-btn" :disabled="phase === 'loading' || !prompt.trim()" @click="onGenerate">
        <span v-if="phase === 'loading'">生成中…</span>
        <span v-else>✨ 生成我的头像</span>
      </button>

      <div v-if="phase === 'error'" class="error-box">
        <div class="error-msg">{{ errorMsg }}</div>
        <button v-if="retryable" class="retry-btn" @click="onGenerate">重试</button>
      </div>
    </section>

    <section class="loading" v-if="phase === 'loading'">
      <div class="spinner"></div>
      <div class="loading-text">正在生成你的专属头像…</div>
    </section>

    <section class="result" v-if="phase === 'result' && display">
      <div class="result-card">
        <img class="result-img" :src="display.src" :alt="display.title" />
        <div class="result-caption">{{ display.caption }}</div>
      </div>
      <div class="result-actions">
        <button class="act primary" @click="regenerate">🔄 再生成</button>
        <button class="act" @click="regenerateSame">✨ 生成同款</button>
        <button class="act" @click="copyPrompt">📋 复制描述</button>
        <button class="act" @click="goHome">🏠 返回首页</button>
      </div>
      <button class="back-form" @click="backToForm">← 修改描述</button>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { generateTemplate, templateResultToDisplay, MAX_PROMPT_LEN, retryDelay, sleep, isFatalError } from './tgApi'
import { haptic } from './telegram'
import type { AspectRatio, DisplayImage } from './types'

const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

type Phase = 'form' | 'loading' | 'result' | 'error'

const prompt = ref('')
const style = ref('')
const mood = ref('')
const scene = ref('')
const aspectRatio: AspectRatio = '1:1'
const phase = ref<Phase>('form')
const errorMsg = ref('')
const retryable = ref(false)
const display = ref<DisplayImage | null>(null)
const toast = ref('')

const styles = [
  { id: 'cinematic', label: '电影感' },
  { id: 'cyberpunk', label: '赛博朋克' },
  { id: 'jp-photo', label: '日系写真' },
  { id: 'business', label: '商务头像' },
  { id: 'guofeng', label: '国风' },
  { id: '3d-cartoon', label: '3D 卡通' },
]
const moods = [
  { id: 'cool', label: '清冷' },
  { id: 'sunny', label: '阳光' },
  { id: 'fierce', label: '酷飒' },
  { id: 'gentle', label: '温柔' },
  { id: 'professional', label: '专业' },
]
const scenes = [
  { id: 'solid', label: '纯色背景' },
  { id: 'city-night', label: '城市夜景' },
  { id: 'natural-light', label: '自然光' },
  { id: 'future-tech', label: '未来科技' },
]

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}

async function onGenerate() {
  const p = prompt.value.trim()
  if (!p) { errorMsg.value = '请输入人物描述'; phase.value = 'error'; retryable.value = false; return }
  phase.value = 'loading'
  errorMsg.value = ''
  haptic('light')
  // 出图偶发失败：后台静默重试直到成功，用户只看到转圈，不展示失败文案。
  // 仅配置类错误（retryable === false）才停止并提示。
  let attempt = 0
  while (phase.value === 'loading') {
    attempt++
    const resp = await generateTemplate({
      template_id: 'avatar-viral',
      input: { prompt: p, style: style.value, mood: mood.value, scene: scene.value, aspect_ratio: aspectRatio },
    })
    if (resp.ok && resp.result) {
      const d = templateResultToDisplay(resp.result)
      if (d) { display.value = d; phase.value = 'result'; haptic('medium'); return }
      await sleep(retryDelay(attempt)); continue
    }
    if (isFatalError(resp.error?.code)) {
      errorMsg.value = resp.error?.message || '服务暂时不可用'; retryable.value = false; phase.value = 'error'; return
    }
    await sleep(retryDelay(attempt))
  }
}

function regenerate() { phase.value = 'form'; display.value = null }
function regenerateSame() { onGenerate() }
function backToForm() { phase.value = 'form' }

async function copyPrompt() {
  const text = display.value?.prompt || prompt.value
  try {
    await navigator.clipboard.writeText(text)
    showToast('描述已复制')
  } catch {
    showToast('复制失败，请手动选择')
  }
}

function goHome() { emit('navigate', '/tg') }
</script>

<style scoped>
.page { max-width: 560px; margin: 0 auto; padding: 0 16px 40px; min-height: 100vh; }
.top { display: flex; align-items: center; padding: 14px 0; position: sticky; top: 0; background: var(--tg-bg, #f7f7fa); z-index: 5; }
.back { font-size: 22px; width: 36px; height: 36px; border: none; background: none; color: var(--tg-text, #333); cursor: pointer; }
.top-title { flex: 1; text-align: center; font-size: 17px; font-weight: 700; color: var(--tg-text, #1a1a1a); }
.top-spacer { width: 36px; }

.hint { font-size: 13px; color: var(--tg-hint, #999); margin: 8px 0 4px; }
.field-label { display: block; font-size: 14px; font-weight: 600; color: var(--tg-text, #333); margin: 18px 0 8px; }
.prompt-input {
  width: 100%; box-sizing: border-box; padding: 14px; border-radius: 14px;
  border: 1.5px solid #e3e3e8; font-size: 15px; resize: none; font-family: inherit;
  background: var(--tg-card, #fff); color: var(--tg-text, #1a1a1a);
}
.prompt-input:focus { outline: none; border-color: #6c5ce7; }
.counter { text-align: right; font-size: 12px; color: var(--tg-hint, #aaa); margin-top: 4px; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  padding: 8px 16px; border-radius: 999px; border: 1.5px solid #e3e3e8;
  background: var(--tg-card, #fff); font-size: 14px; color: var(--tg-text, #444); cursor: pointer;
}
.chip.active { border-color: #6c5ce7; background: #f1eefe; color: #6c5ce7; font-weight: 600; }

.generate-btn {
  width: 100%; margin-top: 26px; padding: 16px; border-radius: 14px; border: none;
  background: linear-gradient(135deg, #6c5ce7, #8e7bf0); color: #fff;
  font-size: 17px; font-weight: 700; cursor: pointer;
}
.generate-btn:disabled { opacity: 0.5; cursor: default; }

.error-box { margin-top: 18px; padding: 14px; border-radius: 12px; background: #fff0f0; }
.error-msg { font-size: 14px; color: #d4380d; }
.retry-btn { margin-top: 10px; padding: 8px 20px; border-radius: 10px; border: none; background: #d4380d; color: #fff; font-size: 14px; cursor: pointer; }

.loading { text-align: center; padding: 48px 0; }
.spinner { width: 40px; height: 40px; margin: 0 auto 16px; border: 3px solid #eee; border-top-color: #6c5ce7; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font-size: 14px; color: var(--tg-hint, #888); }

.result-card { background: var(--tg-card, #fff); border-radius: 16px; overflow: hidden; box-shadow: 0 2px 16px rgba(108,92,231,0.18); margin-top: 8px; padding-top: 20px; text-align: center; }
/* 头像差异化：圆形预览，区别于 ai-image 的方形大图 */
.result-img { width: 220px; height: 220px; border-radius: 50%; object-fit: cover; display: inline-block; background: #f0f0f3; border: 4px solid #f1eefe; }
.result-caption { padding: 14px 16px; font-size: 14px; color: var(--tg-text, #555); }

.result-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.act { padding: 14px; border-radius: 12px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); cursor: pointer; }
.act.primary { grid-column: span 2; background: linear-gradient(135deg, #6c5ce7, #8e7bf0); color: #fff; border: none; font-weight: 700; }

.back-form { width: 100%; margin-top: 16px; padding: 12px; border: none; background: none; color: var(--tg-hint, #888); font-size: 14px; cursor: pointer; }
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 20; }
</style>
