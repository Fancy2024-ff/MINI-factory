<!-- /tg/ai-image：真实可用的 AI 图片生成产品页（移动端优先，Telegram WebApp）。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">AI 图片生成</div>
      <div class="top-spacer"></div>
    </header>

    <!-- 表单 -->
    <section class="form" v-if="phase !== 'result'">
      <label class="field-label">描述你想要的画面</label>
      <textarea
        class="prompt-input"
        v-model="prompt"
        :maxlength="MAX_PROMPT_LEN"
        placeholder="例如：海边日落，温暖的橙色天空，油画质感"
        rows="3"
      ></textarea>
      <div class="counter">{{ prompt.length }}/{{ MAX_PROMPT_LEN }}</div>

      <label class="field-label">风格</label>
      <div class="chips">
        <button
          v-for="s in styles"
          :key="s.id"
          class="chip"
          :class="{ active: style === s.id }"
          @click="style = s.id"
        >{{ s.label }}</button>
      </div>

      <label class="field-label">比例</label>
      <div class="chips">
        <button
          v-for="r in ratios"
          :key="r"
          class="chip"
          :class="{ active: aspectRatio === r }"
          @click="aspectRatio = r"
        >{{ r }}</button>
      </div>

      <button class="generate-btn" :disabled="phase === 'loading' || !prompt.trim()" @click="onGenerate">
        <span v-if="phase === 'loading'">生成中…</span>
        <span v-else>✨ 立即生成</span>
      </button>

      <div v-if="phase === 'error'" class="error-box">
        <div class="error-msg">{{ errorMsg }}</div>
        <button v-if="retryable" class="retry-btn" @click="onGenerate">重试</button>
      </div>
    </section>

    <!-- loading 占位 -->
    <section class="loading" v-if="phase === 'loading'">
      <div class="spinner"></div>
      <div class="loading-text">正在生成，请稍候…</div>
    </section>

    <!-- 结果 -->
    <section class="result" v-if="phase === 'result' && display">
      <div class="result-card">
        <img class="result-img" :src="display.src" :alt="display.title" />
        <div class="result-caption">{{ display.caption }}</div>
      </div>

      <div class="result-actions">
        <button class="act primary" @click="regenerate">🔄 再生成</button>
        <button class="act" @click="regenerateSame">✨ 生成同款</button>
        <button class="act" @click="copyPrompt">📋 复制描述</button>
        <button class="act" @click="share">📤 {{ shareLabel }}</button>
      </div>

      <button class="back-form" @click="backToForm">← 修改描述</button>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { generateImage, toDisplayImage, MAX_PROMPT_LEN } from './tgApi'
import { haptic, shareInTelegram, isInTelegram } from './telegram'
import type { AspectRatio, DisplayImage } from './types'

const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

type Phase = 'form' | 'loading' | 'result' | 'error'

const prompt = ref('')
const style = ref('realistic')
const aspectRatio = ref<AspectRatio>('1:1')
const phase = ref<Phase>('form')
const errorMsg = ref('')
const retryable = ref(false)
const display = ref<DisplayImage | null>(null)
const toast = ref('')

const styles = [
  { id: 'realistic', label: '写实' },
  { id: 'anime', label: '动漫' },
  { id: 'oil', label: '油画' },
  { id: 'watercolor', label: '水彩' },
  { id: '3d', label: '3D' },
  { id: 'cyberpunk', label: '赛博朋克' },
]
const ratios: AspectRatio[] = ['1:1', '4:3', '3:4', '16:9', '9:16']

const shareLabel = isInTelegram() ? '分享给好友' : '分享'

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}

async function onGenerate() {
  const p = prompt.value.trim()
  if (!p) { errorMsg.value = '请输入图片描述'; phase.value = 'error'; retryable.value = false; return }
  phase.value = 'loading'
  errorMsg.value = ''
  haptic('light')
  const resp = await generateImage({
    template_id: 'ai-image',
    prompt: p,
    style: style.value,
    aspect_ratio: aspectRatio.value,
  })
  if (resp.ok && resp.result) {
    const d = toDisplayImage(resp.result)
    if (d) { display.value = d; phase.value = 'result'; haptic('medium'); return }
    errorMsg.value = '生成结果异常，请重试'; retryable.value = true; phase.value = 'error'; return
  }
  errorMsg.value = resp.error?.message || '生成失败，请稍后再试'
  retryable.value = resp.error?.retryable ?? true
  phase.value = 'error'
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

function share() {
  const text = display.value?.prompt || prompt.value
  const shared = shareInTelegram(`我用 MiniForge 生成了「${text}」，你也来试试！`)
  showToast(shared ? '已唤起分享' : '可截图分享给好友')
}

function goHome() { emit('navigate', '/tg') }
</script>

<style scoped>
.page { max-width: 560px; margin: 0 auto; padding: 0 16px 40px; min-height: 100vh; }
.top { display: flex; align-items: center; padding: 14px 0; position: sticky; top: 0; background: var(--tg-bg, #f7f7fa); z-index: 5; }
.back { font-size: 22px; width: 36px; height: 36px; border: none; background: none; color: var(--tg-text, #333); cursor: pointer; }
.top-title { flex: 1; text-align: center; font-size: 17px; font-weight: 700; color: var(--tg-text, #1a1a1a); }
.top-spacer { width: 36px; }

.field-label { display: block; font-size: 14px; font-weight: 600; color: var(--tg-text, #333); margin: 18px 0 8px; }
.prompt-input {
  width: 100%; box-sizing: border-box; padding: 14px; border-radius: 14px;
  border: 1.5px solid #e3e3e8; font-size: 15px; resize: none; font-family: inherit;
  background: var(--tg-card, #fff); color: var(--tg-text, #1a1a1a);
}
.prompt-input:focus { outline: none; border-color: var(--tg-btn, #ff6b35); }
.counter { text-align: right; font-size: 12px; color: var(--tg-hint, #aaa); margin-top: 4px; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  padding: 8px 16px; border-radius: 999px; border: 1.5px solid #e3e3e8;
  background: var(--tg-card, #fff); font-size: 14px; color: var(--tg-text, #444); cursor: pointer;
}
.chip.active { border-color: var(--tg-btn, #ff6b35); background: #fff3ee; color: var(--tg-btn, #ff6b35); font-weight: 600; }

.generate-btn {
  width: 100%; margin-top: 26px; padding: 16px; border-radius: 14px; border: none;
  background: var(--tg-btn, #ff6b35); color: var(--tg-btn-text, #fff);
  font-size: 17px; font-weight: 700; cursor: pointer;
}
.generate-btn:disabled { opacity: 0.5; cursor: default; }

.error-box { margin-top: 18px; padding: 14px; border-radius: 12px; background: #fff0f0; }
.error-msg { font-size: 14px; color: #d4380d; }
.retry-btn { margin-top: 10px; padding: 8px 20px; border-radius: 10px; border: none; background: #d4380d; color: #fff; font-size: 14px; cursor: pointer; }

.loading { text-align: center; padding: 48px 0; }
.spinner { width: 40px; height: 40px; margin: 0 auto 16px; border: 3px solid #eee; border-top-color: var(--tg-btn, #ff6b35); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font-size: 14px; color: var(--tg-hint, #888); }

.result-card { background: var(--tg-card, #fff); border-radius: 16px; overflow: hidden; box-shadow: 0 2px 16px rgba(0,0,0,0.08); margin-top: 8px; }
.result-img { width: 100%; display: block; background: #f0f0f3; }
.result-caption { padding: 14px 16px; font-size: 14px; color: var(--tg-text, #555); }

.result-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.act { padding: 14px; border-radius: 12px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); cursor: pointer; }
.act.primary { grid-column: span 2; background: var(--tg-btn, #ff6b35); color: var(--tg-btn-text, #fff); border: none; font-weight: 700; }

.back-form { width: 100%; margin-top: 16px; padding: 12px; border: none; background: none; color: var(--tg-hint, #888); font-size: 14px; cursor: pointer; }

.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 20; }
</style>
