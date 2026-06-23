<!-- /tg/pet-talk：宠物说话（台词 → 会说话的宠物预览）。
     诚实边界：当前产出静态封面预览，真实「说话视频」为流程预留，页面明确标注。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">宠物说话</div>
      <div class="top-spacer"></div>
    </header>

    <section class="form" v-if="phase !== 'result'">
      <p class="hint">给宠物配一句台词，生成「会说话的宠物」预览</p>

      <div class="notice">
        ⚠️ 当前版本生成<strong>静态预览图</strong>（宠物 + 台词），
        真实「说话视频 / 配音」为流程预留，后续接入视频生成后开放。
      </div>

      <label class="field-label">上传宠物照片（占位，可选）</label>
      <button class="upload-box" @click="onUploadHint">
        <span class="upload-ph">📷 点击上传宠物照片（暂为占位）</span>
      </button>

      <label class="field-label">宠物台词</label>
      <textarea
        class="prompt-input"
        v-model="prompt"
        :maxlength="MAX_PROMPT_LEN"
        placeholder="想让它说什么？如：主人，该喂饭啦！"
        rows="3"
      ></textarea>
      <div class="counter">{{ prompt.length }}/{{ MAX_PROMPT_LEN }}</div>

      <button class="generate-btn" :disabled="phase === 'loading' || !prompt.trim()" @click="onGenerate">
        <span v-if="phase === 'loading'">生成中…</span>
        <span v-else>🐶 生成宠物说话预览</span>
      </button>

      <div v-if="phase === 'error'" class="error-box">
        <div class="error-msg">{{ errorMsg }}</div>
        <button v-if="retryable" class="retry-btn" @click="onGenerate">重试</button>
      </div>
    </section>

    <section class="loading" v-if="phase === 'loading'">
      <div class="spinner"></div>
      <div class="loading-text">正在生成宠物说话预览…</div>
    </section>

    <section class="result" v-if="phase === 'result' && display">
      <div class="result-card">
        <img class="result-img" :src="display.src" :alt="display.title" />
        <div class="preview-badge">静态预览 · 视频生成流程预留</div>
        <div class="result-caption">{{ display.caption }}</div>
      </div>
      <div class="unlock-tip">分享到朋友圈解锁高清 / 去水印（视频版上线后开放）</div>
      <div class="result-actions">
        <button class="act primary" @click="regenerate">🔄 再生成</button>
        <button class="act" @click="regenerateSame">✨ 生成同款</button>
        <button class="act" @click="copyPrompt">📋 复制台词</button>
        <button class="act" @click="goHome">🏠 返回首页</button>
      </div>
      <button class="back-form" @click="backToForm">← 修改台词</button>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { generateTemplate, templateResultToDisplay, MAX_PROMPT_LEN } from './tgApi'
import { haptic } from './telegram'
import type { DisplayImage } from './types'

const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

type Phase = 'form' | 'loading' | 'result' | 'error'

const prompt = ref('')
const phase = ref<Phase>('form')
const errorMsg = ref('')
const retryable = ref(false)
const display = ref<DisplayImage | null>(null)
const toast = ref('')

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}

function onUploadHint() {
  // 上传为占位：当前生成不依赖真实宠物照片，避免给出虚假能力承诺。
  showToast('照片上传为占位，当前先用台词生成预览')
}

async function onGenerate() {
  const p = prompt.value.trim()
  if (!p) { errorMsg.value = '请输入宠物台词'; phase.value = 'error'; retryable.value = false; return }
  phase.value = 'loading'
  errorMsg.value = ''
  haptic('light')
  const resp = await generateTemplate({
    template_id: 'pet-talk-viral',
    input: { prompt: p },
  })
  if (resp.ok && resp.result) {
    const d = templateResultToDisplay(resp.result, '宠物说话预览')
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
    showToast('台词已复制')
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
.notice { margin: 12px 0 4px; padding: 12px 14px; border-radius: 12px; background: #f0f9ff; color: #0369a1; font-size: 13px; line-height: 1.5; }
.notice strong { color: #075985; }
.field-label { display: block; font-size: 14px; font-weight: 600; color: var(--tg-text, #333); margin: 18px 0 8px; }
.upload-box {
  width: 100%; box-sizing: border-box; padding: 22px; border-radius: 14px;
  border: 1.5px dashed #16a34a; background: #f0fdf4; color: #16a34a;
  font-size: 14px; cursor: pointer;
}
.upload-ph { font-size: 14px; }
.prompt-input {
  width: 100%; box-sizing: border-box; padding: 14px; border-radius: 14px;
  border: 1.5px solid #e3e3e8; font-size: 15px; resize: none; font-family: inherit;
  background: var(--tg-card, #fff); color: var(--tg-text, #1a1a1a);
}
.prompt-input:focus { outline: none; border-color: #16a34a; }
.counter { text-align: right; font-size: 12px; color: var(--tg-hint, #aaa); margin-top: 4px; }

.generate-btn {
  width: 100%; margin-top: 26px; padding: 16px; border-radius: 14px; border: none;
  background: linear-gradient(135deg, #16a34a, #22c55e); color: #fff;
  font-size: 17px; font-weight: 700; cursor: pointer;
}
.generate-btn:disabled { opacity: 0.5; cursor: default; }

.error-box { margin-top: 18px; padding: 14px; border-radius: 12px; background: #fff0f0; }
.error-msg { font-size: 14px; color: #d4380d; }
.retry-btn { margin-top: 10px; padding: 8px 20px; border-radius: 10px; border: none; background: #d4380d; color: #fff; font-size: 14px; cursor: pointer; }

.loading { text-align: center; padding: 48px 0; }
.spinner { width: 40px; height: 40px; margin: 0 auto 16px; border: 3px solid #eee; border-top-color: #16a34a; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font-size: 14px; color: var(--tg-hint, #888); }

.result-card { background: var(--tg-card, #fff); border-radius: 16px; overflow: hidden; box-shadow: 0 2px 16px rgba(22,163,74,0.18); margin-top: 8px; text-align: center; position: relative; }
.result-img { width: 100%; display: block; background: #f0f0f3; }
.preview-badge { position: absolute; top: 12px; left: 12px; background: rgba(0,0,0,0.6); color: #fff; font-size: 12px; padding: 4px 10px; border-radius: 999px; }
.result-caption { padding: 14px 16px; font-size: 14px; color: var(--tg-text, #555); }
.unlock-tip { margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: #f0fdf4; color: #15803d; font-size: 13px; text-align: center; }

.result-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.act { padding: 14px; border-radius: 12px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); cursor: pointer; }
.act.primary { grid-column: span 2; background: linear-gradient(135deg, #16a34a, #22c55e); color: #fff; border: none; font-weight: 700; }

.back-form { width: 100%; margin-top: 16px; padding: 12px; border: none; background: none; color: var(--tg-hint, #888); font-size: 14px; cursor: pointer; }
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 20; }
</style>
