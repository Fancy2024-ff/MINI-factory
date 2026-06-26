// 出图下载闸门：下载前先看广告解锁，解锁后同会话内复用。
// 全部出图页共用，避免在各页重复粘贴广告倒计时逻辑。
import { ref } from 'vue'
import { getTelegram, openLink } from './telegram'
import { sendToChat } from './tgApi'

export type DownloadResult = 'downloaded' | 'opened' | 'sent' | 'failed'

// iOS（含 iPadOS）的 Safari/WebKit 对 <a download> 支持极差：data/blob URL 的
// download 属性基本被忽略，点了没反应也不报错。检测出来后改走「新标签打开图片，
// 用户长按存相册」，并如实提示，避免「假保存」。
function isIOS(): boolean {
  const ua = navigator.userAgent || ''
  const iOSUA = /iPad|iPhone|iPod/.test(ua)
  // iPadOS 13+ UA 伪装成 Mac：用「MacIntel + 多点触摸 + 确有触摸事件支持」联合判断，
  // 避免把 Mac 桌面端 / Electron WebView（部分会把 maxTouchPoints 报成 >1）误判为 iOS。
  const iPadOS =
    navigator.platform === 'MacIntel' &&
    (navigator.maxTouchPoints || 0) > 1 &&
    'ontouchend' in document
  return iOSUA || iPadOS
}

// 在新标签打开图片，让用户长按/右键保存。返回是否成功打开。
function openInNewTab(src: string): boolean {
  try {
    const w = window.open(src, '_blank')
    return !!w
  } catch {
    return false
  }
}

// 把图片 src 取成 blob URL。data: 直接转；http(s) 远程图先 fetch（绕开跨域时
// <a download> 被忽略的问题）。失败返回 null。
async function toBlobUrl(src: string): Promise<string | null> {
  try {
    const res = await fetch(src)
    if (!res.ok) return null
    const blob = await res.blob()
    return URL.createObjectURL(blob)
  } catch {
    return null
  }
}

// 把一张 N×N 网格表情大图切成独立小图（data URL）。用于表情包「单个下载/全部下载」。
// 注意：AI 生成的网格并非像素级对齐，等分切图可能带轻微缺边/残影，是已知取舍。
// rows×cols 默认 3×3（后端 sticker sheet 为 3×3 九宫格）。失败返回 []。
export async function sliceGrid(src: string, rows = 3, cols = 3): Promise<string[]> {
  const img = await loadImage(src)
  if (!img) return []
  const cellW = Math.floor(img.naturalWidth / cols)
  const cellH = Math.floor(img.naturalHeight / rows)
  if (cellW <= 0 || cellH <= 0) return []
  const out: string[] = []
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const canvas = document.createElement('canvas')
      canvas.width = cellW
      canvas.height = cellH
      const ctx = canvas.getContext('2d')
      if (!ctx) continue
      ctx.drawImage(img, c * cellW, r * cellH, cellW, cellH, 0, 0, cellW, cellH)
      try {
        out.push(canvas.toDataURL('image/png'))
      } catch {
        // toDataURL 在跨域未授权图上会抛 SecurityError：放弃该格，不污染整体。
      }
    }
  }
  return out
}

// 加载图片并等待 decode（设 crossOrigin 以便 canvas 不被污染）。失败返回 null。
function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = src
  })
}

function triggerAnchorDownload(href: string, filename: string): boolean {
  try {
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    return true
  } catch {
    return false
  }
}

// 把图片下载/保存到设备。处理几类环境：
//  - Telegram 内置 WebView：不支持 <a download>，a.click() 静默失效。
//    远程图 → openLink 交系统浏览器；base64/blob → 通过 bot sendToChat 发到聊天
//    （TG 里唯一真正能落地到相册的路径，避免「假成功但没文件」）。
//  - iOS Safari：<a download> 对 data/blob 基本无效，改为新标签打开让用户长按存相册。
//  - 桌面浏览器：统一先转 blob URL 再下（Safari 对 data URI 下载不稳，blob 才可靠）。
// 返回 'downloaded'（触发了下载）/ 'opened'（转交浏览器/新标签，需用户长按保存）/
//      'sent'（TG 发到聊天）/ 'failed'。
export async function downloadImage(src: string, filename: string): Promise<DownloadResult> {
  const inTelegram = !!getTelegram()

  if (inTelegram) {
    // 远程 URL：交系统浏览器（可长按存相册）。
    if (/^https?:/i.test(src)) {
      if (openLink(src)) return 'opened'
      return triggerAnchorDownload(src, filename) ? 'downloaded' : 'failed'
    }
    // base64 / blob：<a download> 在 TG WebView 不工作，改用 bot 发到聊天。
    const sent = await sendToChat(src, '')
    if (sent.ok) return 'sent'
    // 发送失败（如未配置 / BOT_BLOCKED）：兜底尝试 anchor，至少不更糟。
    return triggerAnchorDownload(src, filename) ? 'downloaded' : 'failed'
  }

  // iOS Safari：download 属性基本被忽略，直接新标签打开让用户长按存相册。
  // 远程图直接开原链接；data/blob 先转 blob URL（新标签能正常渲染大图）。
  if (isIOS()) {
    let openSrc = src
    if (src.startsWith('data:') || src.startsWith('blob:')) {
      const blobUrl = await toBlobUrl(src)
      if (blobUrl) openSrc = blobUrl
    }
    return openInNewTab(openSrc) ? 'opened' : 'failed'
  }

  // 桌面/安卓浏览器：统一转 blob URL 再下。
  // - data URI：Safari 对其 <a download> 不可靠，转 blob 后稳。
  // - 远程图：转 blob 绕开跨域时 download 属性失效。
  const blobUrl = await toBlobUrl(src)
  if (blobUrl) {
    const ok = triggerAnchorDownload(blobUrl, filename)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 10000)
    if (ok) return 'downloaded'
  }
  // 转 blob 失败（如远程图 CORS）：退而求其次直接用原 src 下，至少能触发。
  return triggerAnchorDownload(src, filename) ? 'downloaded' : 'failed'
}

// 看广告解锁下载的闸门。首次下载弹广告倒计时，倒计时结束领取后才真正下载；
// 同一会话解锁一次后，后续下载直接放行。
//
// 广告开关/时长由后端运行时配置（提交中心可改）。页面拿到配置后调 configure()
// 更新；未配置时用默认（启用、30s）。enabled=false 时下载不弹广告，直接放行。
export function useDownloadGate(adSeconds = 30) {
  const adVisible = ref(false)
  const adRemain = ref(0)
  const unlocked = ref(false)
  const enabled = ref(true)
  const seconds = ref(adSeconds)
  const videoUrl = ref('')
  let timer: ReturnType<typeof setInterval> | null = null
  let pending: (() => void) | null = null

  // 运行时套用后端广告配置（可在 mounted 异步 fetch 后调用）。
  function configure(opts: { enabled?: boolean; seconds?: number; videoUrl?: string }) {
    if (typeof opts.enabled === 'boolean') enabled.value = opts.enabled
    if (typeof opts.seconds === 'number' && opts.seconds >= 0) seconds.value = opts.seconds
    if (typeof opts.videoUrl === 'string') videoUrl.value = opts.videoUrl
  }

  // download：真正执行下载的回调（解锁后调用）。
  function requestDownload(download: () => void) {
    // 广告下架 或 时长为 0：不弹闸门，直接下载。
    if (!enabled.value || seconds.value <= 0 || unlocked.value) { download(); return }
    pending = download
    adVisible.value = true
    adRemain.value = seconds.value
    if (timer) clearInterval(timer)
    timer = setInterval(() => {
      adRemain.value--
      if (adRemain.value <= 0 && timer) { clearInterval(timer); timer = null }
    }, 1000)
  }

  // 广告结束后用户点「领取并下载」。
  function claim() {
    if (adRemain.value > 0) return
    unlocked.value = true
    adVisible.value = false
    const fn = pending
    pending = null
    fn?.()
  }

  return { adVisible, adRemain, unlocked, requestDownload, claim, configure, videoUrl }
}
