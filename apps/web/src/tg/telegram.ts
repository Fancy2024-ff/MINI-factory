// 轻量 Telegram WebApp 适配：只用 window.Telegram.WebApp，不引入官方 SDK。
// 不存在时（普通浏览器打开）全部优雅降级，不崩。

interface TgThemeParams {
  bg_color?: string
  text_color?: string
  hint_color?: string
  button_color?: string
  button_text_color?: string
  secondary_bg_color?: string
}

interface TgWebApp {
  ready?: () => void
  expand?: () => void
  themeParams?: TgThemeParams
  colorScheme?: string
  MainButton?: {
    setText?: (t: string) => void
    show?: () => void
    hide?: () => void
    onClick?: (cb: () => void) => void
    offClick?: (cb: () => void) => void
  }
  HapticFeedback?: { impactOccurred?: (style: string) => void }
  openTelegramLink?: (url: string) => void
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void
  switchInlineQuery?: (query: string, types?: string[]) => void
  initData?: string
  platform?: string
  version?: string
}

export function getTelegram(): TgWebApp | null {
  const w = window as any
  return (w?.Telegram?.WebApp as TgWebApp) || null
}

export function isInTelegram(): boolean {
  return getTelegram() !== null
}

// 调 ready()/expand() 并把 themeParams 写到 CSS 变量；无 Telegram 时无副作用。
export function initTelegram(): void {
  const tg = getTelegram()
  if (!tg) return
  try {
    tg.ready?.()
    tg.expand?.()
    const tp = tg.themeParams || {}
    const root = document.documentElement
    if (tp.bg_color) root.style.setProperty('--tg-bg', tp.bg_color)
    if (tp.text_color) root.style.setProperty('--tg-text', tp.text_color)
    if (tp.button_color) root.style.setProperty('--tg-btn', tp.button_color)
    if (tp.button_text_color) root.style.setProperty('--tg-btn-text', tp.button_text_color)
    if (tp.secondary_bg_color) root.style.setProperty('--tg-card', tp.secondary_bg_color)
  } catch {
    /* 任意 Telegram API 异常都不应影响页面 */
  }
}

export function haptic(style: 'light' | 'medium' | 'heavy' = 'light'): void {
  try {
    getTelegram()?.HapticFeedback?.impactOccurred?.(style)
  } catch {
    /* ignore */
  }
}

// 分享：Telegram 内用 switchInlineQuery 提示分享，否则回退到无操作（调用方给文案）。
export function shareInTelegram(text: string): boolean {
  const tg = getTelegram()
  if (tg?.switchInlineQuery) {
    try {
      tg.switchInlineQuery(text, ['users', 'groups'])
      return true
    } catch {
      return false
    }
  }
  return false
}

// 在系统浏览器打开链接。Telegram 内置 WebView 不支持 <a download>，
// 用 openLink 把图片交给系统浏览器/相册保存。返回是否走了 Telegram 通道。
export function openLink(url: string): boolean {
  const tg = getTelegram()
  if (tg?.openLink) {
    try {
      tg.openLink(url)
      return true
    } catch {
      return false
    }
  }
  return false
}

// Telegram WebApp 下发的已签名 initData（后端用 bot token 校验取 chat_id）。
export function getInitData(): string {
  return getTelegram()?.initData || ''
}

// 是否具备「发送到聊天」条件：在 Telegram 内且拿到了 initData。
export function canSendToChat(): boolean {
  return isInTelegram() && getInitData() !== ''
}
