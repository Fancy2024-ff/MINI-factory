// 统一生成服务（blueprint 驱动，API 优先 + mock 兼容）。
//
// 设计：
// - blueprint.json（codegen 由 template.json 合成）是题材事实源：preview_type /
//   mock_examples / share_hooks / unlock_hooks 都从蓝图读取，generation.ts 不再
//   硬编码每个模板的分支。
// - blueprint 缺失/损坏时回退到安全默认值（不崩、不阻断闭环）。
// - 运行模式由 config/api.ts 控制：GENERATION_MODE='api' 且 API_BASE 合法时，
//   **正式生成产物默认优先走真实后端**（/api/generation/template 或 /image）；
//   GENERATION_MODE='mock'（或不支持真实生成的模板）才走本地 mock。
// - 前端只知道 apps/api 地址，绝不接触中转站 URL/key。
//
// 真实链路覆盖（与后端 template_generation SUPPORTED_TEMPLATES 一致）：
//   ai-image / avatar-viral / sticker-viral / pet-talk-viral（pet-talk 为静态封面预览，
//   视频为流程预留）。funny-video-viral / blessing-video-viral 暂无真实视频生成，
//   走「诚实预览型」mock，不伪装成已完成（previewData.honest_fallback=true）。

import { SELECTED_TEMPLATE, PREVIEW_TYPE } from '../config/template'
// blueprint.json 由 codegen 在生成项目时写入（template.json -> blueprint）。
import blueprintJson from '../config/blueprint.json'
import { API_BASE, GENERATION_MODE, IMAGE_GENERATION_PATH, TEMPLATE_GENERATION_PATH } from '../config/api'

// 真实后端覆盖的模板（与后端 template_generation.SUPPORTED_TEMPLATES 对齐）。
const API_TEMPLATES = ['ai-image', 'avatar-viral', 'sticker-viral', 'pet-talk-viral']
// 暂无真实视频生成、走诚实预览型 mock 的模板。
const PREVIEW_ONLY_TEMPLATES = ['funny-video-viral', 'blessing-video-viral']

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

// 真实 API 路径：根据模板调 apps/api 的生成接口。
//   - ai-image            -> POST /api/generation/image    （prompt/style/aspect_ratio）
//   - avatar/sticker/pet-talk -> POST /api/generation/template（template_id + 结构化 input）
// 返回 null 表示该模板不走真实链路（如视频预览型），由调用方走诚实 mock。
async function callRealApi(bp: Blueprint, input: GenerateInput): Promise<GeneratedResult | null> {
  const tpl = bp.template_id
  if (API_TEMPLATES.indexOf(tpl) === -1) return null

  const prompt = (input.text || '').trim()
  const style = (input.extra && input.extra.style) || ''
  const aspectRatio = (input.extra && input.extra.aspect_ratio) || '1:1'

  // ai-image 走 image 专用接口；其余题材模板走 template 接口（结构化 input）。
  const isImage = tpl === 'ai-image'
  const url = API_BASE + (isImage ? IMAGE_GENERATION_PATH : TEMPLATE_GENERATION_PATH)
  const data = isImage
    ? { template_id: tpl, prompt, style, aspect_ratio: aspectRatio }
    : { template_id: tpl, input: { prompt, style, aspect_ratio: aspectRatio, ...(input.extra || {}) } }

  const resp = await new Promise<any>((resolve, reject) => {
    uni.request({
      url,
      method: 'POST',
      data,
      header: { 'Content-Type': 'application/json' },
      success: (r) => resolve(r.data),
      fail: (e) => reject(e),
    })
  })

  if (!resp || !resp.ok || !resp.result) {
    // 后端返回结构化错误，交给上层转友好错误态。
    const msg = (resp && resp.error && resp.error.message) || '生成失败，请稍后重试'
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
  // 真实结果以后端 preview_type 为准（image / avatar / stickerPack / petVideo）。
  const previewType = (resp.preview_type || r.preview_type || bp.preview_type) as PreviewType
  return {
    id: genId(),
    createdAt: Date.now(),
    template: tpl,
    title: r.title || example.title,
    previewType,
    previewData: {
      image: imageUrl,
      image_base64: imageBase64,
      prompt: r.prompt || prompt,
      caption: r.caption || '',
      // pet-talk 等视频预留：后端 video_supported=false 时如实标注
      videoSupported: resp.video_supported !== false ? undefined : false,
    },
    shareTitle: example.share_title || bp.share_hooks[0] || '看看我生成的结果',
    shareCopy: example.share_copy || bp.share_hooks[1] || bp.share_hooks[0] || '',
    unlockHint: example.unlock_hint || bp.unlock_hooks[0] || '分享解锁高清无水印结果',
    watermarkEnabled: true,
    inputSummary: prompt,
    sourceBlueprint: tpl,
    nextActionHint: bp.unlock_hooks[0] || '分享解锁更多',
  }
}

// 诚实预览型 mock（funny-video / blessing-video 等暂无真实视频生成的模板）。
// 明确标注 honest_fallback，前端/QA/产物口径一致，不伪装成已完成真实生成。
function buildHonestPreview(bp: Blueprint, input: GenerateInput): GeneratedResult {
  const base = buildFromBlueprint(bp, input)
  base.previewData = {
    ...(base.previewData || {}),
    honest_fallback: true,
    fallback_note: '当前为预览型结果，真实视频生成为流程预留',
  }
  return { id: genId(), createdAt: Date.now(), ...base }
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

// 正式生成入口。API 优先：mode=api 时支持真实生成的模板走后端；
// 视频预览型模板走诚实 fallback；其余/未配置走本地 mock。
export async function mockGenerate(input: GenerateInput): Promise<GeneratedResult> {
  const bp = loadBlueprint()
  // api 模式：支持真实生成的模板优先走后端真实链路。
  // 真实调用抛错时直接抛给上层，由 form/result 转友好错误态，不静默吞掉。
  if (GENERATION_MODE === 'api') {
    const real = await callRealApi(bp, input)
    if (real) {
      saveResult(real)
      return real
    }
  }
  // 视频预览型模板（funny-video / blessing-video）：诚实预览，不伪装真实视频。
  if (PREVIEW_ONLY_TEMPLATES.indexOf(bp.template_id) !== -1) {
    const preview = buildHonestPreview(bp, input)
    saveResult(preview)
    return preview
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
