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
        <button class="act primary" @click="backToForm">🔄 换一张</button>
        <button class="act" @click="handleDownload">⬇ 下载</button>
      </div>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>

    <!-- 30s 广告倒计时 -->
    <div v-if="adVisible" class="ad-overlay">
      <div class="ad-box">📺</div>
      <div class="ad-countdown">{{ adRemain > 0 ? ('广告 ' + adRemain + 's') : '广告结束 ✓' }}</div>
      <div class="ad-hint">观看广告后即可下载高清图片</div>
      <button class="ad-skip" :disabled="adRemain > 0" @click="finishAd">领取并下载</button>
    </div>
  </div>
</template>
<!-- SCRIPT_PLACEHOLDER -->
<script setup lang="ts">
import { ref } from 'vue'
import { editImage, toDisplayImage, retryDelay, sleep, isFatalError } from './tgApi'
import { haptic } from './telegram'
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
  let attempt = 0
  while (phase.value === 'loading') {
    attempt++
    loadingText.value = LOADING_MSGS[Math.min(attempt - 1, LOADING_MSGS.length - 1)]
    const resp = await editImage(sourceFile.value, { task: 'background_remove' })
    if (resp.ok && resp.result) {
      const d = toDisplayImage(resp.result)
      if (d) { display.value = d; phase.value = 'result'; haptic('medium'); return }
      await sleep(retryDelay(attempt)); continue
    }
    if (isFatalError(resp.error?.code)) {
      errorMsg.value = resp.error?.message || '服务暂时不可用'; phase.value = 'error'; return
    }
    await sleep(retryDelay(attempt))
  }
}

function backToForm() { phase.value = 'form'; display.value = null }
function goHome() { emit('navigate', '/tg') }

// 下载前 30s 广告倒计时
const adVisible = ref(false)
const adRemain = ref(0)
let downloadUnlocked = false
let adTimer: ReturnType<typeof setInterval> | null = null

function handleDownload() {
  if (!display.value) { showToast('还没有可下载的图片'); return }
  if (downloadUnlocked) { doDownload(); return }
  adVisible.value = true
  adRemain.value = 30
  if (adTimer) clearInterval(adTimer)
  adTimer = setInterval(() => {
    adRemain.value--
    if (adRemain.value <= 0) { if (adTimer) clearInterval(adTimer); downloadUnlocked = true }
  }, 1000)
}

function finishAd() {
  if (adRemain.value > 0) return
  adVisible.value = false
  doDownload()
}

function doDownload() {
  try {
    const a = document.createElement('a')
    a.href = display.value!.src
    a.download = 'bg-removed-' + Date.now() + '.png'
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    showToast('已开始下载 ✓')
  } catch {
    showToast('下载失败，请长按图片保存')
  }
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
.ad-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 200; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #fff; padding: 24px; }
.ad-box { width: 100%; max-width: 420px; aspect-ratio: 16/10; background: linear-gradient(135deg,#1f2937,#374151); border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 40px; margin-bottom: 20px; }
.ad-countdown { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.ad-hint { font-size: 13px; color: #9ca3af; }
.ad-skip { margin-top: 18px; border: 1px solid #4b5563; color: #d1d5db; background: none; padding: 8px 18px; border-radius: 20px; }
.ad-skip:disabled { opacity: 0.4; }
</style>