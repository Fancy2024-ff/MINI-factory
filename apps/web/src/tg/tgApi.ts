// TG WebApp 图片生成 API 客户端。
// 只调 public runtime 接口 /api/generation/image，不带 dashboard key。
// 安全：不打印完整 base64 / 完整 image URL；base64 只用于构造 image src。

import type {
  GenerateImageRequest,
  GenerateImageResponse,
  ImageResult,
  DisplayImage,
} from './types'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const MAX_PROMPT_LEN = 500

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
