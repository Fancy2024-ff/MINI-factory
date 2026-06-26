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

      <label class="field-label">生成数量</label>
      <div class="chips">
        <button v-for="n in countOptions" :key="n" class="chip" :class="{ active: count === n }" @click="count = n">{{ n }} 张</button>
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
      <div class="loading-text">{{ loadingText }}</div>
    </section>

    <section class="result" v-if="phase === 'result' && stickers.length">
      <!-- 每张表情独立生成，天然干净无错位。单张直接展示大图，多张排网格。 -->
      <div class="sticker-grid" :class="{ single: stickers.length === 1 }">
        <button
          v-for="(s, i) in stickers"
          :key="i"
          class="sticker-item"
          @click="downloadOne(i)"
        >
          <img :src="s.src" :alt="`表情 ${i + 1}`" />
          <span class="cell-dl">⬇</span>
        </button>
      </div>
      <div class="cell-tip">点任意表情可单独{{ canSend ? '发送/' : '' }}下载</div>

      <div class="unlock-tip">分享到群聊解锁更多表情 / 去水印高清导出</div>
      <div class="result-actions">
        <button v-if="canSend" class="act primary" @click="handleSendAll">📩 全部发送到聊天（{{ stickers.length }}张）</button>
        <button class="act" :class="{ primary: !canSend }" @click="downloadAll">⬇ 全部下载（{{ stickers.length }}张）</button>
        <button class="act" @click="regenerate">🔄 再来一套</button>
        <button class="act" @click="regenerateSame">✨ 生成同款</button>
        <button class="act" @click="copyPrompt">📋 复制主题</button>
        <button class="act" @click="goHome">🏠 返回首页</button>
      </div>
      <button class="back-form" @click="backToForm">← 修改主题</button>
      <div v-if="toast" class="toast">{{ toast }}</div>
    </section>

    <AdGateOverlay :visible="adVisible" :remain="adRemain" :video-url="adVideoUrl" @claim="claim" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { generateTemplate, templateResultToDisplay, MAX_PROMPT_LEN, runUntilImage, sendToChat, fetchAdConfig } from './tgApi'
import { haptic, canSendToChat } from './telegram'
import { useDownloadGate, downloadImage } from './download'
import AdGateOverlay from './AdGateOverlay.vue'
import type { DisplayImage } from './types'

const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

type Phase = 'form' | 'loading' | 'result' | 'error'

const prompt = ref('')
const mood = ref('')
const phase = ref<Phase>('form')
const errorMsg = ref('')
const retryable = ref(false)
const toast = ref('')
const loadingText = ref('正在生成你的表情包…')
// 每张表情独立生成的结果（1 或 4 张），每张天然干净无错位。
const stickers = ref<DisplayImage[]>([])
// 生成数量：只支持 1 / 4（独立出图保证每张完美，不再切大图）。
const countOptions = [1, 4]
const count = ref(1)
// 整套表情的表情动作（做 4 张时逐张不同）。
const SET_EXPRESSIONS = [
  'happy smiling expression',
  'angry grumpy expression',
  'crying sad expression',
  'love heart eyes expression',
]

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
  stickers.value = []
  haptic('light')
  const total = count.value
  const got: DisplayImage[] = []
  // 逐张独立出图：1 张用主题本身，多张则每张指定不同表情动作，保证每张干净且各异。
  for (let i = 0; i < total; i++) {
    loadingText.value = total > 1 ? `正在生成第 ${i + 1}/${total} 张表情…` : '正在生成你的表情…'
    const expression = total > 1 ? SET_EXPRESSIONS[i % SET_EXPRESSIONS.length] : ''
    // 出图偶发失败：后台静默重试直到成功（含退避兜底），不展示失败文案。
    const outcome = await runUntilImage(
      () => generateTemplate({
        template_id: 'sticker-viral',
        input: { prompt: p, mood: mood.value, expression },
      }),
      (result) => templateResultToDisplay(result, '表情已生成'),
      () => phase.value === 'loading',
    )
    if (phase.value !== 'loading') return  // 用户中途离开
    if (outcome.kind === 'ok') {
      got.push(outcome.display)
      stickers.value = [...got]  // 逐张显示，体验更顺
    } else if (outcome.kind === 'fatal') {
      errorMsg.value = outcome.message; retryable.value = false; phase.value = 'error'; return
    }
    // exhausted（单张到兜底上限）：跳过这张，继续后续，不整批失败。
  }
  if (!stickers.value.length) {
    phase.value = 'form'
    showToast('当前生成人数较多，已为你保留主题，请稍后再试一次')
    return
  }
  phase.value = 'result'; haptic('medium')
}

function regenerate() { phase.value = 'form'; stickers.value = [] }
function regenerateSame() { onGenerate() }
function backToForm() { phase.value = 'form' }

async function copyPrompt() {
  const text = stickers.value[0]?.prompt || prompt.value
  try {
    await navigator.clipboard.writeText(text)
    showToast('主题已复制')
  } catch {
    showToast('复制失败，请手动选择')
  }
}

function goHome() { emit('navigate', '/tg') }

// 下载前看广告解锁，解锁后同会话内复用。
const { adVisible, adRemain, requestDownload, claim, configure, videoUrl: adVideoUrl } = useDownloadGate()
// 运行时套用后端广告配置（提交中心可改：开关/时长）。失败兜底默认，不阻塞。
onMounted(async () => { configure(await fetchAdConfig('/tg/sticker')) })

// 下载结果转成「明确告诉用户文件去了哪」的提示，解决「下载完不知道在哪」。
function downloadHint(r: 'downloaded' | 'opened' | 'sent' | 'failed'): string {
  if (r === 'downloaded') return '已保存 ✓ 在手机「下载」目录或相册可找到'
  if (r === 'opened') return '已在浏览器打开，长按图片即可保存到相册'
  if (r === 'sent') return '已发送到聊天 ✓ 点开图片可存相册'
  return '下载失败，请长按图片保存'
}

// 单个表情下载：点网格里的某一张即下载/发送它。
function downloadOne(idx: number) {
  const s = stickers.value[idx]
  if (!s) { showToast('这张表情还没准备好'); return }
  requestDownload(async () => {
    const r = await downloadImage(s.src, `sticker-${idx + 1}-${Date.now()}.png`)
    showToast(downloadHint(r))
  })
}

// 一键全部下载：逐个下载（间隔触发，避免浏览器拦截连续下载）。
function downloadAll() {
  if (!stickers.value.length) { showToast('表情还在准备，请稍候'); return }
  requestDownload(async () => {
    const list = stickers.value
    showToast(`正在下载全部 ${list.length} 张…`)
    for (let i = 0; i < list.length; i++) {
      await downloadImage(list[i].src, `sticker-${i + 1}-${Date.now()}.png`)
      await new Promise((r) => setTimeout(r, 350))
    }
    showToast(`已保存 ${list.length} 张 ✓ 在「下载」目录或相册可找到`)
  })
}

// Telegram 内：把全部表情逐张发到聊天，用户点开即可原生存相册。
const canSend = canSendToChat()
function handleSendAll() {
  if (!stickers.value.length) { showToast('还没有可发送的表情'); return }
  requestDownload(async () => {
    const list = stickers.value
    showToast(list.length > 1 ? `正在发送 ${list.length} 张…` : '正在发送…')
    let ok = 0
    for (let i = 0; i < list.length; i++) {
      const r = await sendToChat(list[i].src, list[i].caption || '')
      if (r.ok) ok++
      else if (r.error?.code === 'BOT_BLOCKED') { showToast('请先在 Bot 中发送任意消息后重试'); return }
      await new Promise((r) => setTimeout(r, 300))
    }
    showToast(ok ? `已发送 ${ok} 张到聊天 ✓ 点开图片可存相册` : '发送失败，请稍后再试')
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

.cell-tip { font-size: 13px; color: var(--tg-hint, #999); text-align: center; margin: 10px 0; }
.sticker-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 8px; }
.sticker-grid.single { grid-template-columns: 1fr; max-width: 320px; margin-left: auto; margin-right: auto; }
.sticker-item {
  position: relative; padding: 0; border: 1.5px solid #e3e3e8; border-radius: 12px;
  background: var(--tg-card, #fff); cursor: pointer; overflow: hidden; aspect-ratio: 1 / 1;
  transition: transform 0.12s, border-color 0.12s;
}
.sticker-item:active { transform: scale(0.96); }
.sticker-item:hover { border-color: #f59e0b; }
.sticker-item img { width: 100%; height: 100%; object-fit: contain; display: block; background: #f6f6f8; }
.cell-dl {
  position: absolute; right: 6px; bottom: 6px; width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.55); color: #fff; border-radius: 999px; font-size: 13px;
}

.result-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.act { padding: 14px; border-radius: 12px; border: 1.5px solid #e3e3e8; background: var(--tg-card, #fff); font-size: 15px; color: var(--tg-text, #333); cursor: pointer; }
.act.primary { grid-column: span 2; background: linear-gradient(135deg, #f59e0b, #fbbf24); color: #fff; border: none; font-weight: 700; }

.back-form { width: 100%; margin-top: 16px; padding: 12px; border: none; background: none; color: var(--tg-hint, #888); font-size: 14px; cursor: pointer; }
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 20; }
</style>
