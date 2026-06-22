// 统一生成服务（本地 mock 闭环，blueprint 驱动，预留真实 API 切换点）。
//
// 设计：
// - blueprint.json（codegen 由 template.json 合成）是题材事实源：preview_type /
//   mock_examples / share_hooks / unlock_hooks 都从蓝图读取，generation.ts 不再
//   硬编码每个模板的分支。
// - blueprint 缺失/损坏时回退到安全默认值（不崩、不阻断闭环）。
// - GENERATION_ENDPOINT 为空 + GENERATION_MODE='mock' 时走本地 mock；
//   后续把 endpoint 指向真实后端、mode 切 'api' 即可启用 callRealApi。不写真实 key。

import { SELECTED_TEMPLATE, PREVIEW_TYPE } from '../config/template'
// blueprint.json 由 codegen 在生成项目时写入（template.json -> blueprint）。
import blueprintJson from '../config/blueprint.json'
import { API_BASE, GENERATION_MODE, IMAGE_GENERATION_PATH } from '../config/api'

export type PreviewType =
  | 'avatar'
  | 'stickerPack'
  | 'petVideo'
  | 'funnyStoryboard'
  | 'blessingCard'
  | 'image'
  | 'text'

export interface MockExample {
  title: string
  preview_type: PreviewType
  preview_data: any
  share_title: string
  share_copy: string
  unlock_hint: string
}

export interface Blueprint {
  template_id: string
  app_name: string
  preview_type: PreviewType
  input_fields: any[]
  pages: string[]
  result_contract: string[]
  share_hooks: string[]
  unlock_hooks: string[]
  growth_angles: string[]
  compliance_notes: string[]
  mock_examples: MockExample[]
  is_fallback: boolean
}

export interface GeneratedResult {
  id: string
  template: string
  title: string
  previewType: PreviewType
  previewData: any
  shareTitle: string
  shareCopy: string
  unlockHint: string
  watermarkEnabled: boolean
  createdAt: number
  // 可选增强字段
  inputSummary?: string
  sourceBlueprint?: string
  nextActionHint?: string
}

export interface GenerateInput {
  text?: string
  assetPlaceholder?: string
  extra?: Record<string, any>
}

// 真实生成模式由 config/api.ts 控制。前端只知道 apps/api 地址，不接触中转站 URL/key。
// 第一阶段真实链路只支持 ai-image / preview_type=image，其余模板继续走 mock。

const STORAGE_PREFIX = 'gen-result:'

// base64 图片保留上限（约 700KB 编码后）：微信单 key storage 上限约 1MB，
// 超过则丢弃 base64、依赖 image_url，避免 setStorageSync 失败丢结果。
const MAX_BASE64_LEN = 700_000

// 安全默认蓝图：blueprint.json 缺失/损坏时兜底，保证闭环不断。
const FALLBACK_BLUEPRINT: Blueprint = {
  template_id: SELECTED_TEMPLATE,
  app_name: '',
  preview_type: (PREVIEW_TYPE as PreviewType) || 'text',
  input_fields: [],
  pages: [],
  result_contract: [],
  share_hooks: ['看看我用它生成的结果', '一键生成，分享解锁完整高清结果'],
  unlock_hooks: ['分享解锁高清无水印结果', '分享解锁更多模板'],
  growth_angles: [],
  compliance_notes: [],
  mock_examples: [{
    title: '生成结果',
    preview_type: (PREVIEW_TYPE as PreviewType) || 'text',
    preview_data: { text: '这是一段示例生成结果。' },
    share_title: '看看我用它生成的结果',
    share_copy: '一键生成，分享解锁完整高清结果',
    unlock_hint: '分享解锁高清无水印结果 + 解锁更多模板',
  }],
  is_fallback: true,
}

let _blueprintCache: Blueprint | null = null

// 读取生成项目内的 blueprint.json；缺字段用安全默认值补齐。
export function loadBlueprint(): Blueprint {
  if (_blueprintCache) return _blueprintCache
  try {
    const bp = blueprintJson as unknown as Blueprint
    _blueprintCache = { ...FALLBACK_BLUEPRINT, ...bp }
  } catch (e) {
    _blueprintCache = FALLBACK_BLUEPRINT
  }
  return _blueprintCache
}

function genId(): string {
  return 'g-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e6).toString(36)
}

// PLACEHOLDER_GENERATION_BODY

// 由 blueprint 的 mock_example + 用户输入合成一个 GeneratedResult（不含 id/createdAt）。
function buildFromBlueprint(
  bp: Blueprint,
  input: GenerateInput,
): Omit<GeneratedResult, 'id' | 'createdAt'> {
  const example = bp.mock_examples[0] || FALLBACK_BLUEPRINT.mock_examples[0]
  const text = (input.text || '').trim()

  // 把用户输入浅合并进 mock 的 preview_data，让结果随输入变化（仍是本地 mock）。
  const previewData = { ...(example.preview_data || {}) }
  if (text) {
    if ('note' in previewData) previewData.note = `风格关键词：${text}`
    else if ('theme' in previewData) previewData.theme = text
    else if ('line' in previewData) previewData.line = text
    else if ('topic' in previewData) previewData.topic = text
    else if ('message' in previewData) previewData.message = text
    else if ('text' in previewData) previewData.text = text
  }
  if (input.extra) {
    if (input.extra.to !== undefined) previewData.to = input.extra.to
    if (input.extra.festival !== undefined) previewData.festival = input.extra.festival
  }

  const shareTitle = example.share_title || bp.share_hooks[0] || '看看我生成的结果'
  const shareCopy = example.share_copy || bp.share_hooks[1] || bp.share_hooks[0] || ''
  const unlockHint = example.unlock_hint || bp.unlock_hooks[0] || '分享解锁高清无水印结果'

  return {
    template: bp.template_id,
    title: example.title,
    previewType: (example.preview_type || bp.preview_type) as PreviewType,
    previewData,
    shareTitle,
    shareCopy,
    unlockHint,
    watermarkEnabled: true,
    inputSummary: text || (input.assetPlaceholder ? '已上传素材' : ''),
    sourceBlueprint: bp.template_id,
    nextActionHint: bp.unlock_hooks[0] || '分享解锁更多',
  }
}

// 真实 API 路径：调 apps/api 的 /api/generation/image（仅 ai-image / image 预览）。
// 返回 null 表示不走真实链路（非 ai-image 或未配置），由调用方回退 mock。
async function callRealApi(bp: Blueprint, input: GenerateInput): Promise<GeneratedResult | null> {
  // 第一阶段真实链路只覆盖 ai-image / preview_type=image。
  if (bp.template_id !== 'ai-image' || bp.preview_type !== 'image') return null

  const prompt = (input.text || '').trim()
  const style = (input.extra && input.extra.style) || ''
  const aspectRatio = (input.extra && input.extra.aspect_ratio) || '1:1'

  const resp = await new Promise<any>((resolve, reject) => {
    uni.request({
      url: API_BASE + IMAGE_GENERATION_PATH,
      method: 'POST',
      data: { template_id: bp.template_id, prompt, style, aspect_ratio: aspectRatio },
      header: { 'Content-Type': 'application/json' },
      success: (r) => resolve(r.data),
      fail: (e) => reject(e),
    })
  })

  if (!resp || !resp.ok || !resp.result) {
    // 后端返回结构化错误，交给上层转友好错误态。
    const msg = (resp && resp.error && resp.error.message) || '图片生成失败，请稍后重试'
    throw new Error(msg)
  }

  const r = resp.result
  const example = bp.mock_examples[0] || FALLBACK_BLUEPRINT.mock_examples[0]
  // 微信小程序单 key storage 上限约 1MB。优先用 image_url；base64 仅在无 url 且
  // 体积可控时保留，避免 setStorageSync 超限导致结果丢失。
  const imageUrl = r.image_url || ''
  let imageBase64 = ''
  if (!imageUrl && r.image_base64 && r.image_base64.length <= MAX_BASE64_LEN) {
    imageBase64 = r.image_base64
  }
  return {
    id: genId(),
    createdAt: Date.now(),
    template: bp.template_id,
    title: example.title,
    previewType: 'image',
    previewData: { image: imageUrl, image_base64: imageBase64, prompt: r.prompt },
    shareTitle: example.share_title,
    shareCopy: example.share_copy,
    unlockHint: example.unlock_hint,
    watermarkEnabled: true,
    inputSummary: prompt,
    sourceBlueprint: bp.template_id,
    nextActionHint: bp.unlock_hooks[0] || '分享解锁更多',
  }
}

// blueprint 驱动的生成入口。
export async function generateFromBlueprint(
  bp: Blueprint,
  input: GenerateInput,
): Promise<GeneratedResult> {
  const result: GeneratedResult = {
    id: genId(),
    createdAt: Date.now(),
    ...buildFromBlueprint(bp, input),
  }
  saveResult(result)
  return result
}

export async function mockGenerate(input: GenerateInput): Promise<GeneratedResult> {
  const bp = loadBlueprint()
  // api 模式：先走真实链路；返回 null（不支持的模板）才回退 mock。
  // 真实调用抛错时直接抛给上层，由 form/result 转友好错误态，不静默吞掉。
  if (GENERATION_MODE === 'api') {
    const real = await callRealApi(bp, input)
    if (real) {
      saveResult(real)
      return real
    }
  }
  // 本地 mock：模拟一点生成耗时
  await new Promise((r) => setTimeout(r, 600))
  return generateFromBlueprint(bp, input)
}

export function saveResult(result: GeneratedResult): void {
  try {
    uni.setStorageSync(STORAGE_PREFIX + result.id, result)
  } catch (e) {
    // ignore storage errors in mock mode
  }
}

export function loadResult(id: string): GeneratedResult | null {
  try {
    return (uni.getStorageSync(STORAGE_PREFIX + id) as GeneratedResult) || null
  } catch (e) {
    return null
  }
}

// 解锁（本地 mock）：去水印 + 标记已解锁。
export function unlockResult(id: string): GeneratedResult | null {
  const r = loadResult(id)
  if (!r) return null
  r.watermarkEnabled = false
  saveResult(r)
  return r
}
