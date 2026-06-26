<!-- /tg/bg-remove：背景去除（image-to-image，上传图→抠图）。静默重试，下载前看广告。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">背景去除</div>
      <div class="top-spacer"></div>
    </header>

    <!-- 上传/表单 -->
    <section class="form" v-if="phase === 'form'">
      <label class="field-label">上传需要去背景的图片</label>
      <div class="uploader" :class="{ 'has-img': !!sourcePreview }" @click="pickFile">
        <img v-if="sourcePreview" :src="sourcePreview" class="src-preview" alt="原图" />
        <div v-else class="uploader-hint">
          <div class="up-icon">⬆️</div>
          <div>点击选择图片</div>
          <div class="up-sub">PNG / JPG / WebP，≤ 12MB</div>
        </div>
      </div>
      <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" class="file-hidden" @change="onFileChange" />

      <button class="generate-btn" :disabled="!sourceFile" @click="onRemove">✨ 一键去背景</button>
    </section>

    <!-- loading -->
    <section class="loading" v-if="phase === 'loading'">
      <div class="spinner"></div>
      <div class="loading-text">{{ loadingText }}</div>
    </section>

    <!-- error（仅配置类） -->
    <section class="form" v-if="phase === 'error'">
      <div class="error-box"><div class="error-msg">{{ errorMsg }}</div></div>
      <button class="generate-btn" @click="backToForm">← 重新上传</button>
    </section>

    <!-- 结果 -->
    <section class="result" v-if="phase === 'result' && display">
      <div class="result-card checker">
        <img class="result-img" :src="display.src" alt="去背景结果" />
      </div>
      <div class="result-actions">
        <button v-if="canSend" class="act primary" @click="handleSendToChat">📩 发送到聊天</button>
        <button class="act" @click="backToForm">🔄 换一张</button>
        <button class="act" @click="handleDownload">⬇ 下载</button>
      </div>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>

    <AdGateOverlay :visible="adVisible" :remain="adRemain" :video-url="adVideoUrl" @claim="claim" />
  </div>
</template>
<!-- SCRIPT_PLACEHOLDER -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { editImage, toDisplayImage, runUntilImage, sendToChat, fetchAdConfig } from './tgApi'
import { haptic, canSendToChat } from './telegram'
import { useDownloadGate, downloadImage } from './download'
import AdGateOverlay from './AdGateOverlay.vue'
import type { DisplayImage } from './types'

const emit = defineEmits<{ (e: 'navigate', path: string): void }>()
type Phase = 'form' | 'loading' | 'result' | 'error'

const phase = ref<Phase>('form')
const errorMsg = ref('')
const display = ref<DisplayImage | null>(null)
const toast = ref('')
const loadingText = ref('正在去除背景，请稍候…')
const LOADING_MSGS = ['正在去除背景，请稍候…', 'AI 正在抠图…', '正在精修边缘…', '马上就好…']

const fileInput = ref<HTMLInputElement | null>(null)
const sourceFile = ref<Blob | null>(null)
const sourcePreview = ref('')

const MAX_BYTES = 12 * 1024 * 1024

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}
function pickFile() { fileInput.value?.click() }

function onFileChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  if (f.size > MAX_BYTES) { errorMsg.value = '图片过大（上限 12MB）'; phase.value = 'error'; return }
  sourceFile.value = f
  sourcePreview.value = URL.createObjectURL(f)
  errorMsg.value = ''
  phase.value = 'form'
}

async function onRemove() {
  if (!sourceFile.value) { showToast('请先上传图片'); return }
  phase.value = 'loading'
  errorMsg.value = ''
  haptic('light')
  // 抠图偶发失败：后台静默重试直到成功，只转圈，不展示失败文案。
  // 退避对齐后端限流并设兜底上限（见 tgApi.runUntilImage），避免永久转圈/自锁死。
  const outcome = await runUntilImage(
    () => editImage(sourceFile.value as Blob, { task: 'background_remove' }),
    (result) => toDisplayImage(result),
    () => phase.value === 'loading',
    (attempt) => { loadingText.value = LOADING_MSGS[Math.min(attempt - 1, LOADING_MSGS.length - 1)] },
  )
  if (phase.value !== 'loading') return
  if (outcome.kind === 'ok') {
    display.value = outcome.display; phase.value = 'result'; haptic('medium'); return
  }
  if (outcome.kind === 'fatal') {
    errorMsg.value = outcome.message; phase.value = 'error'; return
  }
  // exhausted：到达兜底上限仍未出图。不弹失败，温和收尾回到表单。
  phase.value = 'form'
  showToast('当前处理人数较多，请稍后再试一次')
}

function backToForm() { phase.value = 'form'; display.value = null }
function goHome() { emit('navigate', '/tg') }

// 下载前看广告解锁，解锁后同会话内复用。
const { adVisible, adRemain, requestDownload, claim, configure, videoUrl: adVideoUrl } = useDownloadGate()
onMounted(async () => { configure(await fetchAdConfig('/tg/bg-remove')) })

function handleDownload() {
  if (!display.value) { showToast('还没有可下载的图片'); return }
  requestDownload(async () => {
    const r = await downloadImage(display.value!.src, 'bg-removed-' + Date.now() + '.png')
    if (r === 'downloaded') showToast('已开始下载 ✓')
    else if (r === 'opened') showToast('已在浏览器打开，长按图片即可保存')
    else if (r === 'sent') showToast('已发送到聊天 ✓ 点开图片可存相册')
    else showToast('下载失败，请长按图片保存')
  })
}

// Telegram 内：把图发到聊天，用户点开即可原生存相册。复用同一看广告解锁闸门。
const canSend = canSendToChat()
function handleSendToChat() {
  if (!display.value) { showToast('还没有可发送的图片'); return }
  requestDownload(async () => {
    showToast('正在发送…')
    const r = await sendToChat(display.value!.src, display.value!.caption || '')
    if (r.ok) showToast('已发送到聊天 ✓ 点开图片可存相册')
    else if (r.error?.code === 'BOT_BLOCKED') showToast('请先在 Bot 中发送任意消息后重试')
    else showToast('发送失败，请稍后再试')
  })
}

// 供测试驱动（jsdom 无真实 file input）。
defineExpose({ sourceFile, sourcePreview, onRemove, phase })
</script>

<style scoped>
.page { max-width: 560px; margin: 0 auto; padding: 0 16px 40px; min-height: 100vh; }
.top { display: flex; align-items: center; padding: 14px 0; position: sticky; top: 0; background: var(--tg-bg, #f7f7fa); z-index: 5; }
.back { font-size: 22px; width: 36px; height: 36px; border: none; background: none; color: var(--tg-text, #333); cursor: pointer; }
.top-title { flex: 1; text-align: center; font-size: 17px; font-weight: 700; color: var(--tg-text, #1a1a1a); }
.top-spacer { width: 36px; }
.field-label { display: block; font-size: 14px; font-weight: 600; color: var(--tg-text, #333); margin: 18px 0 8px; }
.uploader { width: 100%; min-height: 200px; border: 2px dashed #d0d0d8; border-radius: 16px; display: flex; align-items: center; justify-content: center; background: var(--tg-card, #fff); cursor: pointer; overflow: hidden; }
.uploader.has-img { border-style: solid; padding: 0; }
.uploader-hint { text-align: center; color: var(--tg-hint, #999); }
.up-icon { font-size: 34px; margin-bottom: 8px; }
.up-sub { font-size: 12px; margin-top: 4px; color: #bbb; }
.src-preview { width: 100%; max-height: 320px; object-fit: contain; display: block; }
.file-hidden { display: none; }
.generate-btn { width: 100%; margin-top: 22px; padding: 16px; border-radius: 14px; border: none; background: var(--tg-btn, #ff6b35); color: var(--tg-btn-text, #fff); font-size: 17px; font-weight: 700; cursor: pointer; }
.generate-btn:disabled { opacity: 0.5; cursor: default; }
.error-box { margin-top: 18px; padding: 14px; border-radius: 12px; background: #fff0f0; }
.error-msg { font-size: 14px; color: #d4380d; }
.loading { text-align: center; padding: 48px 0; }
.spinner { width: 40px; height: 40px; margin: 0 auto 16px; border: 3px solid #eee; border-top-color: var(--tg-btn, #ff6b35); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font-size: 14px; color: var(--tg-hint, #888); }
.result-card { background: var(--tg-card, #fff); border-radius: 16px; overflow: hidden; box-shadow: 0 2px 16px rgba(0,0,0,0.08); margin-top: 8px; }
/* 棋盘格底，凸显透明/去背效果 */
.checker { background-image: linear-gradient(45deg,#e8e8ee 25%,transparent 25%),linear-gradient(-45deg,#e8e8ee 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e8e8ee 75%),linear-gradient(-45deg,transparent 75%,#e8e8ee 75%); background-size: 20px 20px; background-position: 0 0,0 10px,10px -10px,-10px 0; }
.result-img { width: 100%; display: block; }
.result-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.act { padding: 14px; border-radius: 12px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); cursor: pointer; }
.act.primary { background: var(--tg-btn, #ff6b35); color: var(--tg-btn-text, #fff); border: none; font-weight: 700; }
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 20; }
</style>