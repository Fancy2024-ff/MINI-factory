<!-- /tg/gen/{id}：工厂生成功能的通用渲染器。按 feature.ability 走真实后端。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">{{ feature?.title || '功能' }}</div>
      <div class="top-spacer"></div>
    </header>

    <section v-if="!feature" class="form">
      <div class="error-box"><div class="error-msg">功能不存在</div></div>
      <button class="generate-btn" @click="goHome">← 返回首页</button>
    </section>

    <section v-else-if="phase !== 'result'" class="form">
      <template v-if="feature.ability === 'img2img'">
        <label class="field-label">{{ feature.ui.uploadLabel || '上传图片' }}</label>
        <div class="uploader" :class="{ 'has-img': !!sourcePreview }" @click="pickFile">
          <img v-if="sourcePreview" :src="sourcePreview" class="src-preview" alt="原图" />
          <div v-else class="uploader-hint"><div class="up-icon">⬆️</div><div>点击选择图片</div></div>
        </div>
        <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp"
               class="file-hidden" @change="onFileChange" />
      </template>
      <template v-else>
        <label class="field-label">{{ feature.ui.textPlaceholder || '描述你想要的画面' }}</label>
        <textarea class="prompt-input" v-model="prompt" :maxlength="MAX_PROMPT_LEN"
                  :placeholder="feature.ui.textPlaceholder" rows="3"></textarea>
      </template>
      <button class="generate-btn" :disabled="phase === 'loading' || !canSubmit" @click="onSubmit">
        <span v-if="phase === 'loading'">生成中…</span>
        <span v-else>✨ {{ feature.ui.submitLabel }}</span>
      </button>
      <div v-if="phase === 'error'" class="error-box"><div class="error-msg">{{ errorMsg }}</div></div>
    </section>

    <section v-if="phase === 'loading'" class="loading">
      <div class="spinner"></div><div class="loading-text">正在处理，请稍候…</div>
    </section>

    <section v-if="phase === 'result' && display" class="result">
      <div class="result-card"><img class="result-img" :src="display.src" :alt="display.title" /></div>
      <button class="generate-btn" @click="backToForm">🔄 再来一次</button>
    </section>
  </div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { generateImage, editImage, toDisplayImage, MAX_PROMPT_LEN,
         runUntilImage } from './tgApi'
import { getFeatureById, type FeatureConfig } from './registry/featureRegistry'
import type { DisplayImage } from './types'

const props = defineProps<{ featureId: string }>()
const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

const feature = computed<FeatureConfig | undefined>(() => getFeatureById(props.featureId))
type Phase = 'form' | 'loading' | 'result' | 'error'
const phase = ref<Phase>('form')
const errorMsg = ref('')
const display = ref<DisplayImage | null>(null)
const prompt = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const sourceFile = ref<Blob | null>(null)
const sourcePreview = ref('')

const canSubmit = computed(() =>
  feature.value?.ability === 'img2img' ? !!sourceFile.value : !!prompt.value.trim())

function pickFile() { fileInput.value?.click() }
function onFileChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  sourceFile.value = f
  sourcePreview.value = URL.createObjectURL(f)
}

async function onSubmit() {
  if (!feature.value || !canSubmit.value) return
  phase.value = 'loading'; errorMsg.value = ''
  const f = feature.value
  const outcome = await runUntilImage(
    () => f.ability === 'img2img'
      ? editImage(sourceFile.value!, { task: f.params.task || f.task })
      : generateImage({ prompt: (f.params.promptTemplate || '{input}').replace('{input}', prompt.value), template_id: 'ai-image', style: '', aspect_ratio: '1:1' }),
    (r) => toDisplayImage(r),
    () => phase.value === 'loading',
  )
  if (outcome.kind === 'ok') { display.value = outcome.display; phase.value = 'result' }
  else if (outcome.kind === 'fatal') { errorMsg.value = outcome.message; phase.value = 'error' }
  else { errorMsg.value = '稍后再试'; phase.value = 'error' }
}

function backToForm() { phase.value = 'form'; display.value = null }
function goHome() { emit('navigate', '/tg') }
defineExpose({ feature, phase, onSubmit })
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
.prompt-input { width: 100%; box-sizing: border-box; padding: 14px; border-radius: 14px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); resize: vertical; font-family: inherit; }
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

