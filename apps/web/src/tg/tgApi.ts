// TG WebApp 图片生成 API 客户端。
// 只调 public runtime 接口 /api/generation/image，不带 dashboard key。
// 安全：不打印完整 base64 / 完整 image URL；base64 只用于构造 image src。

import type {
  GenerateImageRequest,
  GenerateImageResponse,
  ImageResult,
  DisplayImage,
  TemplateGenerationRequest,
  TemplateGenerationResponse,
  TemplateResult,
  ApiError,
} from './types'
import { getInitData } from './telegram'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const MAX_PROMPT_LEN = 500

// 重试退避：起步即拉长，确保 60s 窗口内请求数 < 后端限流上限（10次/60s/IP），
// 否则快重试会把限流窗口持续打满，导致“永久转圈、永远出不来”的自锁死。
// 指数退避 3s→12s 封顶：60s 内约 3~4 次请求，稳在限流线以下。
export function retryDelay(attempt: number): number {
  return Math.min(3000 * Math.pow(1.5, attempt - 1), 12000)
}

// 兜底上限：对用户表现为“一直转圈直到出图”，但内部设最长时长上限。
// 到顶仍未出图 → 不弹失败，由调用方温和收尾（保留输入、提示稍后再试）。
export const MAX_RETRY_MS = 90_000

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// 只有这些“真·永久错误”才停止重试并提示用户——重试再多也没用：
// 后端未配置 provider、鉴权失败。其余（provider 抽风返回空图 MALFORMED、
// 超时 TIMEOUT、服务暂时不可用 PROVIDER_FAILED、网络）都视为瞬时失败，静默重试。
// 注意：不直接信任后端的 retryable 字段——后端把 MALFORMED_RESPONSE 误标为
// retryable=false，但它其实是 provider 偶发空响应，应当继续重试。
const FATAL_ERROR_CODES = new Set<string>([
  'IMAGE_GENERATION_NOT_CONFIGURED',
  'IMAGE_GENERATION_AUTH_FAILED',
])

export function isFatalError(code: string | undefined): boolean {
  return !!code && FATAL_ERROR_CODES.has(code)
}

// 共享出图重试 helper：对用户表现为“转圈直到出图”，绝不展示失败文案。
// - 成功（拿到可展示图）→ 'ok'
// - 配置类 fatal 错误（再试无用）→ 'fatal'
// - 到达兜底上限仍未出图 → 'exhausted'（调用方温和收尾，不弹“失败”）
// 退避优先用后端 retry_after（限流场景），否则用对齐限流的指数退避，避免自锁死。
export type RetryOutcome =
  | { kind: 'ok'; display: DisplayImage }
  | { kind: 'fatal'; message: string }
  | { kind: 'exhausted' }

export async function runUntilImage(
  doRequest: () => Promise<{ ok: boolean; result?: any; error?: import('./types').ApiError }>,
  toDisplay: (result: any) => DisplayImage | null,
  shouldContinue: () => boolean,
  onAttempt?: (attempt: number) => void,
): Promise<RetryOutcome> {
  const deadline = Date.now() + MAX_RETRY_MS
  let attempt = 0
  while (shouldContinue()) {
    attempt++
    if (onAttempt) onAttempt(attempt)
    const resp = await doRequest()
    if (resp.ok && resp.result) {
      const d = toDisplay(resp.result)
      if (d) return { kind: 'ok', display: d }
      // ok 但无可展示图（provider 偶发空响应）：视为瞬时失败，继续重试。
    } else if (isFatalError(resp.error?.code)) {
      return { kind: 'fatal', message: resp.error?.message || '服务暂时不可用' }
    }
    // 限流时优先听后端的 retry_after；否则用对齐限流的指数退避。
    const retryAfterMs =
      resp.error?.retry_after != null ? resp.error.retry_after * 1000 : retryDelay(attempt)
    // 已超兜底上限：不再发起新请求，交调用方温和收尾。
    if (Date.now() + retryAfterMs >= deadline) return { kind: 'exhausted' }
    await sleep(retryAfterMs)
  }
  return { kind: 'exhausted' }
}

export async function generateImage(
  req: GenerateImageRequest,
): Promise<GenerateImageResponse> {
  try {
    const res = await fetch(`${BASE}/api/generation/image`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    if (!res.ok) {
      return {
        ok: false,
        error: { code: 'HTTP_ERROR', message: '服务暂时不可用，请稍后再试', retryable: true },
      }
    }
    return (await res.json()) as GenerateImageResponse
  } catch {
    // 网络错误，不泄露内部细节
    return {
      ok: false,
      error: { code: 'NETWORK_ERROR', message: '网络异常，请检查连接后重试', retryable: true },
    }
  }
}

// 图像编辑（背景去除等 image-to-image）：上传图片到后端 /api/generation/image-edit。
// 后端调 provider /images/edits；key 留服务器。返回与 generateImage 同形。
export async function editImage(
  file: Blob,
  opts: { task?: string; prompt?: string; filename?: string } = {},
): Promise<GenerateImageResponse> {
  try {
    const form = new FormData()
    form.append('image', file, opts.filename || 'image.png')
    form.append('task', opts.task || 'background_remove')
    if (opts.prompt) form.append('prompt', opts.prompt)
    const res = await fetch(`${BASE}/api/generation/image-edit`, {
      method: 'POST',
      body: form,
    })
    if (!res.ok) {
      return {
        ok: false,
        error: { code: 'HTTP_ERROR', message: '服务暂时不可用，请稍后再试', retryable: true },
      }
    }
    return (await res.json()) as GenerateImageResponse
  } catch {
    return {
      ok: false,
      error: { code: 'NETWORK_ERROR', message: '网络异常，请检查连接后重试', retryable: true },
    }
  }
}

// 把生成图发到用户的 Telegram 聊天（可在聊天中存相册）。
// init_data 由 telegram.getInitData 提供，后端用 bot token 校验取 chat_id。
export async function sendToChat(
  imageSrc: string,
  caption = '',
): Promise<{ ok: boolean; error?: ApiError }> {
  try {
    const res = await fetch(`${BASE}/api/generation/send-to-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: getInitData(), image_src: imageSrc, caption }),
    })
    if (!res.ok) {
      return { ok: false, error: { code: 'HTTP_ERROR', message: '发送失败，请稍后再试', retryable: true } }
    }
    return (await res.json()) as { ok: boolean; error?: ApiError }
  } catch {
    return { ok: false, error: { code: 'NETWORK_ERROR', message: '网络异常，请稍后再试', retryable: true } }
  }
}

// 把后端 result 规范化为可直接展示的图片；优先 image_url，其次 base64。
// 返回 null 表示无可展示图片（调用方转错误态）。
export function toDisplayImage(result: ImageResult | undefined): DisplayImage | null {
  if (!result) return null
  let src = ''
  if (result.image_url) {
    src = result.image_url
  } else if (result.image_base64) {
    // base64 只在此处构造成 data URI，不打日志、不存 localStorage
    src = `data:image/jpeg;base64,${result.image_base64}`
  }
  if (!src) return null
  return {
    src,
    title: result.title || 'AI 图片生成',
    caption: result.caption || result.prompt || '',
    prompt: result.prompt || '',
  }
}

// 模板级生成：POST /api/generation/template。结构化 input 由后端 adapter 改写。
export async function generateTemplate(
  req: TemplateGenerationRequest,
): Promise<TemplateGenerationResponse> {
  try {
    const res = await fetch(`${BASE}/api/generation/template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    if (!res.ok) {
      return {
        ok: false,
        error: { code: 'HTTP_ERROR', message: '服务暂时不可用，请稍后再试', retryable: true },
      }
    }
    return (await res.json()) as TemplateGenerationResponse
  } catch {
    return {
      ok: false,
      error: { code: 'NETWORK_ERROR', message: '网络异常，请检查连接后重试', retryable: true },
    }
  }
}

// 模板 result（与 image result 同形）规范化为展示图。
export function templateResultToDisplay(
  result: TemplateResult | undefined,
  fallbackTitle = 'AI 头像已生成',
): DisplayImage | null {
  if (!result) return null
  let src = ''
  if (result.image_url) {
    src = result.image_url
  } else if (result.image_base64) {
    src = `data:image/jpeg;base64,${result.image_base64}`
  }
  if (!src) return null
  return {
    src,
    title: result.title || fallbackTitle,
    caption: result.caption || result.prompt || '',
    prompt: result.prompt || '',
  }
}
