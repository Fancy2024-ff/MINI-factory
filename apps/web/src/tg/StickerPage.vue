<!-- /tg/sticker：表情包生成（一个主题/情绪 → 一组贴纸预览）。移动端优先。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">表情包工厂</div>
      <div class="top-spacer"></div>
    </header>

    <section class="form" v-if="phase !== 'result'">
      <p class="hint">输入一个主题，生成一整套搞怪表情包贴纸</p>

      <label class="field-label">表情主题</label>
      <textarea
        class="prompt-input"
        v-model="prompt"
        :maxlength="MAX_PROMPT_LEN"
        placeholder="例如：打工人 / 猫猫 / 怼人专用"
        rows="2"
      ></textarea>
      <div class="counter">{{ prompt.length }}/{{ MAX_PROMPT_LEN }}</div>

      <label class="field-label">情绪倾向</label>
      <div class="chips">
        <button v-for="m in moods" :key="m.id" class="chip" :class="{ active: mood === m.id }" @click="mood = mood === m.id ? '' : m.id">{{ m.label }}</button>
      </div>

      <button class="generate-btn" :disabled="phase === 'loading' || !prompt.trim()" @click="onGenerate">
        <span v-if="phase === 'loading'">生成中…</span>
        <span v-else>😄 生成表情包</span>
      </button>

      <div v-if="phase === 'error'" class="error-box">
        <div class="error-msg">{{ errorMsg }}</div>
        <button v-if="retryable" class="retry-btn" @click="onGenerate">重试</button>
      </div>
    </section>

    <section class="loading" v-if="phase === 'loading'">
      <div class="spinner"></div>
      <div class="loading-text">正在生成你的表情包…</div>
    </section>

    <section class="result" v-if="phase === 'result' && display">
      <div class="result-card">
        <img class="result-img" :src="display.src" :alt="display.title" />
        <div class="result-caption">{{ display.caption }}</div>
      </div>

      <!-- 单个表情网格：切好后点任意一张即可单独下载（解决「想单独下某个」） -->
      <div v-if="cells.length" class="cell-block">
        <div class="cell-tip">点任意表情可单独下载</div>
        <div class="cell-grid">
          <button
            v-for="(c, i) in cells"
            :key="i"
            class="cell-item"
            @click="downloadOne(i)"
          >
            <img :src="c" :alt="`表情 ${i + 1}`" />
            <span class="cell-dl">⬇</span>
          </button>
        </div>
      </div>
      <div v-else-if="slicing" class="cell-tip cell-tip--loading">正在切分单个表情…</div>

      <div class="unlock-tip">分享到群聊解锁更多表情 / 去水印高清导出</div>
      <div class="result-actions">
        <button v-if="canSend" class="act primary" @click="handleSendToChat">📩 发送到聊天（可存相册）</button>
        <button v-if="cells.length" class="act" :class="{ primary: !canSend }" @click="downloadAll">⬇ 全部下载（{{ cells.length }}张）</button>
        <button class="act" @click="handleDownload">🖼 下载整张大图</button>
        <button class="act" @click="regenerate">🔄 再来一套</button>
        <button class="act" @click="regenerateSame">✨ 生成同款</button>
        <button class="act" @click="copyPrompt">📋 复制主题</button>
        <button class="act" @click="goHome">🏠 返回首页</button>
      </div>
      <button class="back-form" @click="backToForm">← 修改主题</button>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>

    <AdGateOverlay :visible="adVisible" :remain="adRemain" @claim="claim" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { generateTemplate, templateResultToDisplay, MAX_PROMPT_LEN, runUntilImage, sendToChat } from './tgApi'
import { haptic, canSendToChat } from './telegram'
import { useDownloadGate, downloadImage, sliceGrid } from './download'
import AdGateOverlay from './AdGateOverlay.vue'
import type { DisplayImage } from './types'

const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

type Phase = 'form' | 'loading' | 'result' | 'error'

const prompt = ref('')
const mood = ref('')
const phase = ref<Phase>('form')
const errorMsg = ref('')
const retryable = ref(false)
const display = ref<DisplayImage | null>(null)
const toast = ref('')
// 切好的单个表情（9 宫格 → 9 张），点单个下载 / 一键全部下载用。
const cells = ref<string[]>([])
const slicing = ref(false)

const moods = [
  { id: '搞笑', label: '搞笑' },
  { id: '可爱', label: '可爱' },
  { id: '暴躁', label: '暴躁' },
  { id: '治愈', label: '治愈' },
]

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}

async function onGenerate() {
  const p = prompt.value.trim()
  if (!p) { errorMsg.value = '请输入表情主题'; phase.value = 'error'; retryable.value = false; return }
  phase.value = 'loading'
  errorMsg.value = ''
  haptic('light')
  // 出图偶发失败：后台静默重试直到成功，用户只看到转圈，不展示失败文案。
  // 退避对齐后端限流并设兜底上限（见 tgApi.runUntilImage），避免永久转圈/自锁死。
  const outcome = await runUntilImage(
    () => generateTemplate({
      template_id: 'sticker-viral',
      input: { prompt: p, mood: mood.value },
    }),
    (result) => templateResultToDisplay(result, '表情包已生成'),
    () => phase.value === 'loading',
  )
  if (phase.value !== 'loading') return
  if (outcome.kind === 'ok') {
    display.value = outcome.display; phase.value = 'result'; haptic('medium')
    sliceCells()
    return
  }
  if (outcome.kind === 'fatal') {
    errorMsg.value = outcome.message; retryable.value = false; phase.value = 'error'; return
  }
  phase.value = 'form'
  showToast('当前生成人数较多，已为你保留主题，请稍后再试一次')
}

function regenerate() { phase.value = 'form'; display.value = null; cells.value = [] }
function regenerateSame() { onGenerate() }
function backToForm() { phase.value = 'form' }

// 把整张 9 宫格大图切成 9 个独立表情，供单个/全部下载。失败则保持空（仍可整张下载）。
async function sliceCells() {
  if (!display.value) return
  slicing.value = true
  cells.value = []
  try {
    cells.value = await sliceGrid(display.value.src, 3, 3)
  } catch {
    cells.value = []
  } finally {
    slicing.value = false
  }
}

async function copyPrompt() {
  const text = display.value?.prompt || prompt.value
  try {
    await navigator.clipboard.writeText(text)
    showToast('主题已复制')
  } catch {
    showToast('复制失败，请手动选择')
  }
}

function goHome() { emit('navigate', '/tg') }

// 下载前看广告解锁，解锁后同会话内复用。
const { adVisible, adRemain, requestDownload, claim } = useDownloadGate()

// 下载结果转成「明确告诉用户文件去了哪」的提示，解决「下载完不知道在哪」。
function downloadHint(r: 'downloaded' | 'opened' | 'sent' | 'failed'): string {
  if (r === 'downloaded') return '已保存 ✓ 在手机「下载」目录或相册可找到'
  if (r === 'opened') return '已在浏览器打开，长按图片即可保存到相册'
  if (r === 'sent') return '已发送到聊天 ✓ 点开图片可存相册'
  return '下载失败，请长按图片保存'
}

// 整张 9 宫格大图下载（兜底：切图失败时仍可用）。
function handleDownload() {
  if (!display.value) { showToast('还没有可下载的表情'); return }
  requestDownload(async () => {
    const r = await downloadImage(display.value!.src, 'sticker-' + Date.now() + '.png')
    showToast(downloadHint(r))
  })
}

// 单个表情下载：点网格里的某一张即下载它。
function downloadOne(idx: number) {
  const src = cells.value[idx]
  if (!src) { showToast('这张表情还没准备好'); return }
  requestDownload(async () => {
    const r = await downloadImage(src, `sticker-${idx + 1}-${Date.now()}.png`)
    showToast(downloadHint(r))
  })
}

// 一键全部下载：把切好的 9 张逐个下载（间隔触发，避免浏览器拦截连续下载）。
function downloadAll() {
  if (!cells.value.length) { showToast('表情还在准备，请稍候'); return }
  requestDownload(async () => {
    const list = cells.value
    showToast(`正在下载全部 ${list.length} 张…`)
    for (let i = 0; i < list.length; i++) {
      await downloadImage(list[i], `sticker-${i + 1}-${Date.now()}.png`)
      await new Promise((r) => setTimeout(r, 350))
    }
    showToast(`已保存 ${list.length} 张 ✓ 在「下载」目录或相册可找到`)
  })
}

// Telegram 内：把图发到聊天，用户点开即可原生存相册。复用同一看广告解锁闸门。
const canSend = canSendToChat()
function handleSendToChat() {
  if (!display.value) { showToast('还没有可发送的表情'); return }
  requestDownload(async () => {
    showToast('正在发送…')
    const r = await sendToChat(display.value!.src, display.value!.caption || '')
    if (r.ok) showToast('已发送到聊天 ✓ 点开图片可存相册')
    else if (r.error?.code === 'BOT_BLOCKED') showToast('请先在 Bot 中发送任意消息后重试')
    else showToast('发送失败，请稍后再试')
  })
}
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
.prompt-input:focus { outline: none; border-color: #f59e0b; }
.counter { text-align: right; font-size: 12px; color: var(--tg-hint, #aaa); margin-top: 4px; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  padding: 8px 16px; border-radius: 999px; border: 1.5px solid #e3e3e8;
  background: var(--tg-card, #fff); font-size: 14px; color: var(--tg-text, #444); cursor: pointer;
}
.chip.active { border-color: #f59e0b; background: #fff7e6; color: #b45309; font-weight: 600; }

.generate-btn {
  width: 100%; margin-top: 26px; padding: 16px; border-radius: 14px; border: none;
  background: linear-gradient(135deg, #f59e0b, #fbbf24); color: #fff;
  font-size: 17px; font-weight: 700; cursor: pointer;
}
.generate-btn:disabled { opacity: 0.5; cursor: default; }

.error-box { margin-top: 18px; padding: 14px; border-radius: 12px; background: #fff0f0; }
.error-msg { font-size: 14px; color: #d4380d; }
.retry-btn { margin-top: 10px; padding: 8px 20px; border-radius: 10px; border: none; background: #d4380d; color: #fff; font-size: 14px; cursor: pointer; }

.loading { text-align: center; padding: 48px 0; }
.spinner { width: 40px; height: 40px; margin: 0 auto 16px; border: 3px solid #eee; border-top-color: #f59e0b; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font-size: 14px; color: var(--tg-hint, #888); }

.result-card { background: var(--tg-card, #fff); border-radius: 16px; overflow: hidden; box-shadow: 0 2px 16px rgba(245,158,11,0.18); margin-top: 8px; text-align: center; }
.result-img { width: 100%; display: block; background: #f0f0f3; }
.result-caption { padding: 14px 16px; font-size: 14px; color: var(--tg-text, #555); }
.unlock-tip { margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: #fff7e6; color: #b45309; font-size: 13px; text-align: center; }

.cell-block { margin-top: 16px; }
.cell-tip { font-size: 13px; color: var(--tg-hint, #999); text-align: center; margin-bottom: 10px; }
.cell-tip--loading { margin-top: 16px; }
.cell-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.cell-item {
  position: relative; padding: 0; border: 1.5px solid #e3e3e8; border-radius: 12px;
  background: var(--tg-card, #fff); cursor: pointer; overflow: hidden; aspect-ratio: 1 / 1;
  transition: transform 0.12s, border-color 0.12s;
}
.cell-item:active { transform: scale(0.96); }
.cell-item:hover { border-color: #f59e0b; }
.cell-item img { width: 100%; height: 100%; object-fit: contain; display: block; background: #f6f6f8; }
.cell-dl {
  position: absolute; right: 4px; bottom: 4px; width: 22px; height: 22px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.55); color: #fff; border-radius: 999px; font-size: 12px;
}

.result-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.act { padding: 14px; border-radius: 12px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); cursor: pointer; }
.act.primary { grid-column: span 2; background: linear-gradient(135deg, #f59e0b, #fbbf24); color: #fff; border: none; font-weight: 700; }

.back-form { width: 100%; margin-top: 16px; padding: 12px; border: none; background: none; color: var(--tg-hint, #888); font-size: 14px; cursor: pointer; }
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 20; }
</style>
