// Telegram WebApp ai-image 类型定义。

export type AspectRatio = '1:1' | '4:3' | '3:4' | '16:9' | '9:16'

export interface ImageStyleOption {
  id: string
  label: string
}

export interface GenerateImageRequest {
  template_id: 'ai-image'
  prompt: string
  style: string
  aspect_ratio: AspectRatio
}

// 后端 /api/generation/image 成功返回的 result。
export interface ImageResult {
  preview_type: 'image'
  title?: string
  caption?: string
  image_url?: string | null
  image_base64?: string | null
  prompt?: string
  provider?: string
  created_at?: number
  metadata?: Record<string, any>
}

export interface ApiError {
  code: string
  message: string
  retryable?: boolean
}

export interface GenerateImageResponse {
  ok: boolean
  result?: ImageResult
  error?: ApiError
}

// 前端规范化后的展示用结果：src 已构造好，绝不在别处拼 base64。
export interface DisplayImage {
  src: string
  title: string
  caption: string
  prompt: string
}
