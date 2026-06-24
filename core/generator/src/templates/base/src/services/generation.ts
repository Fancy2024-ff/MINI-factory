// 统一生成服务（blueprint 驱动，按模板能力状态执行）。
//
// 设计：
// - blueprint.json（codegen 由 template.json 合成）是题材+能力事实源：preview_type /
//   template_status / generation_backend / real_generation / fallback_mode /
//   boundary_note / mock_examples / share_hooks 都从蓝图读取。
// - blueprint 缺失/损坏时回退到安全默认值（不崩、不阻断闭环）。
// - 运行模式由 config/api.ts 控制：GENERATION_MODE='api' 且 API_BASE 合法时，
//   核心模板默认优先走真实后端（/api/generation/template 或 /image）。
// - 前端只知道 apps/api 地址，绝不接触中转站 URL/key。
//
// 模板能力两类（与后端 template_generation / template.json 口径一致）：
//   A. 核心可跑通（core_runnable + template_api + real_generation=true）：
//      ai-image / avatar-viral / sticker-viral / pet-talk-viral。走真实后端；
//      真实调用失败时降级本地预览，但显式标记 apiFailed + fallbackMode，不伪装成功。
//      （pet-talk 产出宠物说话预览/封面，动态视频为后续增强边界，非 fallback。）
//   B. 诚实边界型（honest_preview + honest_fallback + real_generation=false）：
//      funny-video-viral / blessing-video-viral。永远走 honest fallback / preview，
//      只产出 storyboard/card 预览，绝不伪装成「视频已生成」。

import { SELECTED_TEMPLATE, PREVIEW_TYPE } from '../config/template'
// blueprint.json 由 codegen 在生成项目时写入（template.json -> blueprint）。
import blueprintJson from '../config/blueprint.json'
import { API_BASE, GENERATION_MODE, IMAGE_GENERATION_PATH, TEMPLATE_GENERATION_PATH } from '../config/api'
// 激励广告配置（codegen 注入）：未配置时 enabled=false + 空 id，运行时诚实提示。
import { REWARDED_AD_UNIT_ID, REWARDED_AD_ENABLED } from '../config/ads'
// 下载漏斗埋点：广告闭环每一步可观测、失败原因可区分（纯本地，不依赖外部服务）。
import { trackGrowthEvent, growthContextFromResult } from './analytics'

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

// 结构化传播闭环事实源（template.json.growth_loop -> blueprint -> 运行时）。
// 这是「这套小程序带不带传播机制」的单一事实源：分享 CTA / 解锁 / 水印 / 去水印 /
// 品牌露出 / 下载导出 / 能力真实度，全部结构化，不靠页面硬编码通用文案。
export interface DownloadGate {
  enabled: boolean
  gate_type: 'rewarded_ad' | 'none'
  ad_unit_id?: string
  required_for: string[]   // download | remove_watermark | export
  gate_label: string       // 未解锁文案，如「看广告下载高清无水印」
  reward_label: string     // 已解锁文案
  unavailable_hint: string // 广告未配置/不可用提示
  close_hint: string       // 用户中途关闭提示
}

export interface GrowthLoop {
  has_share_cta: boolean
  share_cta_label: string
  share_title: string
  share_copy: string
  has_unlock: boolean
  unlock_type: string
  unlock_hint: string
  has_watermark: boolean
  watermark_label: string
  remove_watermark_supported: boolean
  remove_watermark_condition?: string
  brand_exposure: boolean
  brand_label: string
  download_supported: boolean
  export_supported: boolean
  export_label: string
  capability_mode: 'real' | 'fallback_preview'
  capability_note: string
  result_layer_logic?: string
  // 激励广告下载门槛（P0-2）：下载/去水印/导出前需看完 rewarded video ad。
  download_gate?: DownloadGate
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
  // 模板能力真实状态（codegen 从 template.json 注入，前端/QA 口径一致）。
  template_status?: 'core_runnable' | 'honest_preview'
  status_label?: string
  generation_backend?: 'template_api' | 'honest_fallback'
  real_generation?: boolean
  fallback_mode?: boolean
  result_identity?: string
  boundary_note?: string
  frontend_badge?: string
  // 结构化传播闭环事实源（P0-2）。
  growth_loop?: GrowthLoop
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
  // 已分享解锁标记（去水印能力由 removeWatermarkSupported 决定，解锁不必然去水印）。
  unlocked?: boolean
  // 模板能力真实状态（与 blueprint / 后端返回口径一致，结果页据此展示真实/预览）。
  templateStatus?: 'core_runnable' | 'honest_preview'
  generationBackend?: 'template_api' | 'honest_fallback'
  realGeneration?: boolean
  fallbackMode?: boolean
  boundaryNote?: string
  qaStatus?: string
  qaHint?: string
  // 结构化传播闭环（P0-2）：从 blueprint.growth_loop 透传，结果页据此展示
  // 分享 CTA / 解锁 / 水印 / 去水印 / 品牌露出 / 下载导出 / 能力真实度，不靠硬编码。
  growthLoop?: GrowthLoop
  hasShareCta?: boolean
  shareCtaLabel?: string
  hasUnlock?: boolean
  unlockType?: string
  hasWatermark?: boolean
  watermarkLabel?: string
  removeWatermarkSupported?: boolean
  removeWatermarkCondition?: string
  brandExposure?: boolean
  brandLabel?: string
  downloadSupported?: boolean
  exportSupported?: boolean
  exportLabel?: string
  capabilityMode?: 'real' | 'fallback_preview'
  capabilityNote?: string
  // 激励广告下载门槛（P0-2）：下载高清/去水印前需看完 rewarded video ad。
  downloadGate?: DownloadGate
  adUnlocked?: boolean        // 看完广告后置 true
  downloadUnlocked?: boolean  // 看完广告后置 true（下载/导出放行）
  adUnlockRequired?: boolean  // 该结果是否需要广告解锁才能下载
  videoUrl?: string           // 真实视频 URL（仅当后端返回，目前预留）
  // API 失败降级标记：true 表示核心模板真实链路失败、临时回退本地预览，不伪装成功。
  apiFailed?: boolean
  fallbackReason?: string
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

// 表单输入归一（纯函数，便于单测）：把 blueprint.input_fields + 用户填写
// 归一成 { text, extra, assetPlaceholder, valid, missingRequired }。规则（P0-1 收口）：
// - mainText = 第一个 text/textarea 字段（必填优先）的值，作为 prompt/text；
// - 所有非 image 字段都按 id 写入 extra（含 primary 字段本身，避免主字段语义丢失，
//   例如 avatar 的 style 必须同时进 text 和 extra.style）；
// - image 字段仅占位（drives_generation=false）：只产出 assetPlaceholder 标记，
//   不进 extra、不作为生成输入；
// - required 校验：所有 required 且 type!==image 的字段必须有值（text/textarea 看
//   values，select 看 selected）；缺失项进 missingRequired，valid=false；
// - 无 required 字段时退回「至少有 mainText 或任一非 image 字段有值」；
// - 占位图片永远不参与 valid 判断。
export interface FormField {
  id: string
  type?: string
  required?: boolean
  options?: any[]
  drives_generation?: boolean
}

export interface BuiltGenerateInput {
  text: string
  extra: Record<string, any>
  assetPlaceholder: string
  valid: boolean
  missingRequired: string[]
}

export function buildGenerateInput(
  fields: FormField[],
  values: Record<string, string>,
  selected: Record<string, string>,
  assetPicked: Record<string, boolean>,
): BuiltGenerateInput {
  const list = Array.isArray(fields) ? fields : []
  const textFields = list.filter((f) => f.type === 'text' || f.type === 'textarea')
  const primary = textFields.find((f) => f.required) || textFields[0] || null

  const valueOf = (f: FormField): string => {
    if (f.type === 'select') return (selected[f.id] || '').trim()
    return (values[f.id] || '').trim()
  }

  const mainText = primary ? valueOf(primary) : ''

  // 所有非 image 字段都进 extra（含 primary），保证主字段语义不丢。
  const extra: Record<string, any> = {}
  for (const f of list) {
    if (f.type === 'image') continue
    const v = valueOf(f)
    if (v) extra[f.id] = v
  }

  // 占位图片：仅作辅助标记，不参与 valid，也不作为生成输入。
  const hasPlaceholderAsset = list.some((f) => f.type === 'image' && assetPicked[f.id] === true)
  const assetPlaceholder = hasPlaceholderAsset ? '素材占位（不参与生成）' : ''

  // required 校验：所有 required 且非 image 的字段必须有值（image 无真实上传链，不算）。
  const missingRequired: string[] = []
  for (const f of list) {
    if (!f.required || f.type === 'image') continue
    if (!valueOf(f)) missingRequired.push(f.id)
  }

  // 有 required 字段：必须全部满足才有效；
  // 无 required 字段：退回「至少有真实输入」（mainText 或任一非 image 字段）。
  const hasRequired = list.some((f) => f.required && f.type !== 'image')
  const valid = missingRequired.length === 0 && (
    hasRequired ? true : (!!mainText || Object.keys(extra).length > 0)
  )

  return { text: mainText, extra, assetPlaceholder, valid, missingRequired }
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
  // 兜底蓝图默认按通用预览处理，不冒充真实生成。
  template_status: 'honest_preview',
  status_label: '通用预览',
  generation_backend: 'honest_fallback',
  real_generation: false,
  fallback_mode: true,
  boundary_note: '通用兜底模板：当前仅提供通用预览，非题材化真实生成。',
  frontend_badge: '通用预览',
  // 通用兜底传播闭环：保证结果页始终能读到结构化 growth_loop，但不冒充 viral。
  growth_loop: {
    has_share_cta: true,
    share_cta_label: '分享结果',
    share_title: '看看我用它生成的结果',
    share_copy: '一键生成，分享解锁完整高清结果',
    has_unlock: true,
    unlock_type: 'share_to_unlock',
    unlock_hint: '分享解锁高清无水印结果',
    has_watermark: true,
    watermark_label: 'MiniForge 水印',
    remove_watermark_supported: true,
    remove_watermark_condition: '分享后解锁去水印结果',
    brand_exposure: true,
    brand_label: 'MiniForge 出品 · 结果附小程序码',
    download_supported: false,
    export_supported: false,
    export_label: '导出入口已预留',
    capability_mode: 'fallback_preview',
    capability_note: '通用兜底模板：当前仅提供通用预览，非题材化真实生成。',
    result_layer_logic: '结果页展示通用文本结果 + 含水印预览，分享 CTA 引导传播，解锁后去水印。',
  },
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

// growth_loop（结构化传播闭环事实源）-> GeneratedResult 扁平字段。
// 三条生成路径（本地 mock / 真实 API 成功 / API 失败降级）都用它，保证结果页拿到的
// 分享 CTA / 解锁 / 水印 / 去水印 / 品牌 / 导出 / 能力真实度始终来自事实源、口径一致。
function growthFields(bp: Blueprint): Partial<GeneratedResult> {
  const gl = bp.growth_loop || FALLBACK_BLUEPRINT.growth_loop!
  const gate = gl.download_gate
  return {
    growthLoop: gl,
    hasShareCta: gl.has_share_cta,
    shareCtaLabel: gl.share_cta_label,
    hasUnlock: gl.has_unlock,
    unlockType: gl.unlock_type,
    hasWatermark: gl.has_watermark,
    watermarkLabel: gl.watermark_label,
    removeWatermarkSupported: gl.remove_watermark_supported,
    removeWatermarkCondition: gl.remove_watermark_condition,
    brandExposure: gl.brand_exposure,
    brandLabel: gl.brand_label,
    downloadSupported: gl.download_supported,
    exportSupported: gl.export_supported,
    exportLabel: gl.export_label,
    capabilityMode: gl.capability_mode,
    capabilityNote: gl.capability_note,
    // 激励广告门槛（P0-2）：透传 gate + 是否需要广告解锁（未解锁初始态）。
    downloadGate: gate,
    adUnlockRequired: !!(gate && gate.enabled && gate.gate_type === 'rewarded_ad'),
    adUnlocked: false,
    downloadUnlocked: false,
  }
}

// API 失败降级时，把传播闭环（含 growthLoop 对象 + 扁平字段）整体降级为 fallback_preview，
// 杜绝「flat capabilityMode=fallback_preview 但 growthLoop.capability_mode=real、
// exportSupported=true」这类事实源口径冲突（P0-2 finding #2）。
// 降级后是一张本地预览、没有真实高清图：导出/下载一律不支持，去水印仅针对当前本地预览。
function downgradeGrowthLoopForFallback(bp: Blueprint, reason: string): Partial<GeneratedResult> {
  const src = bp.growth_loop || FALLBACK_BLUEPRINT.growth_loop!
  const note = `真实生成暂时不可用，当前为本地预览（${reason}）。导出/下载不可用，去水印仅针对当前本地预览。`
  const downgraded: GrowthLoop = {
    ...src,
    capability_mode: 'fallback_preview',
    capability_note: note,
    // 本地预览无真实文件可导出/下载，如实降为 false。
    download_supported: false,
    export_supported: false,
    export_label: '导出入口已预留',
    // 去水印仅针对当前本地预览，文案说明清楚，不承诺真实高清去水印。
    remove_watermark_condition: src.remove_watermark_supported
      ? '分享解锁去水印（仅针对当前本地预览）'
      : src.remove_watermark_condition,
  }
  return {
    growthLoop: downgraded,
    hasShareCta: downgraded.has_share_cta,
    shareCtaLabel: downgraded.share_cta_label,
    hasUnlock: downgraded.has_unlock,
    unlockType: downgraded.unlock_type,
    hasWatermark: downgraded.has_watermark,
    watermarkLabel: downgraded.watermark_label,
    removeWatermarkSupported: downgraded.remove_watermark_supported,
    removeWatermarkCondition: downgraded.remove_watermark_condition,
    brandExposure: downgraded.brand_exposure,
    brandLabel: downgraded.brand_label,
    downloadSupported: downgraded.download_supported,
    exportSupported: downgraded.export_supported,
    exportLabel: downgraded.export_label,
    capabilityMode: downgraded.capability_mode,
    capabilityNote: downgraded.capability_note,
  }
}

// PLACEHOLDER_GENERATION_BODY

// --- 导出能力判定（纯函数，供 result.vue 行为复用 + 单测，finding #1/#3）---
// 把「这个结果到底能怎么导出」从 UI 抽出成可测纯函数：
// 把「这个结果到底能怎么导出」从 UI 抽出成可测纯函数：
//   remote_video  -> 有 http(s) 视频 URL，可 downloadFile + saveVideoToPhotosAlbum；
//   remote_image  -> 有 http(s) 图片 URL，可 downloadFile + saveImageToPhotosAlbum；
//   text          -> 脚本/祝福卡/通用文本，可 setClipboardData 复制；
//   none          -> 仅 base64 无 URL / 无可导出内容，无真实导出路径。
// 关键约束：exportSupported=true 的结果必须 classifyExportTarget !== 'none'，
// 否则就是假承诺（base64-only 假导出正是栽在这里）。
export type ExportKind = 'remote_video' | 'remote_image' | 'text' | 'none'

export function buildExportText(result: Partial<GeneratedResult>): string {
  const pd: any = (result && result.previewData) || {}
  // 搞笑脚本分镜
  if (result.previewType === 'funnyStoryboard' && Array.isArray(pd.shots)) {
    const head = pd.topic ? `主题：${pd.topic}\n` : ''
    return head + pd.shots.map((s: any) => `${s.t} ${s.desc}`).join('\n')
  }
  // 祝福卡
  if (result.previewType === 'blessingCard') {
    return [pd.to ? `致 ${pd.to}` : '', pd.festival || '', pd.message || '']
      .filter(Boolean)
      .join('\n')
  }
  // 通用文本
  if (typeof pd.text === 'string' && pd.text) return pd.text
  // 兜底：标题 + 分享文案
  return [result.title, result.shareCopy].filter(Boolean).join('\n')
}

export function classifyExportTarget(
  result: Partial<GeneratedResult>,
): { kind: ExportKind; image?: string; video?: string; text?: string } {
  const pd: any = (result && result.previewData) || {}
  // 1. 远程视频 URL（仅当后端真返回 video_url / result.videoUrl）：可存相册。
  const videoUrl = (result && result.videoUrl) || pd.video_url || pd.video || ''
  if (typeof videoUrl === 'string' && /^https?:\/\//.test(videoUrl)) {
    return { kind: 'remote_video', video: videoUrl }
  }
  // 2. 远程图片 URL：可真实保存相册。
  if (typeof pd.image === 'string' && /^https?:\/\//.test(pd.image)) {
    return { kind: 'remote_image', image: pd.image }
  }
  // 3. 文本型结果：可复制。base64-only（无 URL）不算可导出图片，落到文本/none。
  const text = buildExportText(result)
  if (text) return { kind: 'text', text }
  return { kind: 'none' }
}

// base64-only（真实生成成功但只有 base64、无可保存 URL）：图片可渲染、realGeneration 保持 true，
// 但没有稳定文件可存相册，导出能力如实降级（finding #1，方案 B）。同步 growthLoop 对象 + 扁平字段，
// 避免「flat exportSupported=false 但 growthLoop.export_supported=true」的口径冲突。
function downgradeExportForBase64Only(bp: Blueprint): Partial<GeneratedResult> {
  const src = bp.growth_loop || FALLBACK_BLUEPRINT.growth_loop!
  const label = '图片 URL 缺失，暂不可导出'
  const downgraded: GrowthLoop = {
    ...src,
    download_supported: false,
    export_supported: false,
    export_label: label,
  }
  return {
    growthLoop: downgraded,
    downloadSupported: false,
    exportSupported: false,
    exportLabel: label,
  }
}

// 当前构建未配置真实 API（GENERATION_MODE!=='api'），核心模板走本地 mock 时的本地预览态。
// 模板事实源支持真实生成（real_generation=true），但「本次运行结果」并非真实生成：
// 必须整体降级为 fallback_preview / local preview，导出/下载不可用，不显示 real（finding #2）。
function buildLocalPreviewFallback(bp: Blueprint, input: GenerateInput): GeneratedResult {
  const base = buildFromBlueprint(bp, input)
  const reason = '当前构建未配置真实生成 API，展示本地预览'
  base.previewData = {
    ...(base.previewData || {}),
    local_preview: true,
    mock_preview: true,
    fallback_note: reason,
  }
  return {
    id: genId(),
    createdAt: Date.now(),
    ...base,
    // 「事实源支持真实生成」≠「本次运行是真实生成」：本地 mock 必须如实标 fallback_preview。
    realGeneration: false,
    fallbackMode: true,
    // 传播闭环整体降级（含 growthLoop 对象 + 扁平 capability/export 字段），口径一致。
    ...downgradeGrowthLoopForFallback(bp, reason),
    qaHint: 'local preview (no real API configured)',
  }
}

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

  // growth_loop 作为传播文案的优先事实源：有结构化 share/unlock 文案时优先用它，
  // 没有则回退到 mock_example / share_hooks，保证三条路径口径统一。
  const gl = bp.growth_loop
  const gf = growthFields(bp)

  return {
    template: bp.template_id,
    title: example.title,
    previewType: (example.preview_type || bp.preview_type) as PreviewType,
    previewData,
    shareTitle: (gl && gl.share_title) || shareTitle,
    shareCopy: (gl && gl.share_copy) || shareCopy,
    unlockHint: (gl && gl.unlock_hint) || unlockHint,
    // 水印初始态来自事实源 has_watermark，而非硬编码 true（finding #6）。
    watermarkEnabled: gl ? gl.has_watermark !== false : true,
    // 模板能力真实状态：从 blueprint 透传，前端据此展示真实/预览，不靠猜。
    templateStatus: bp.template_status,
    generationBackend: bp.generation_backend,
    realGeneration: bp.real_generation,
    fallbackMode: bp.fallback_mode,
    boundaryNote: bp.boundary_note,
    // 结构化传播闭环字段（P0-2）。
    ...gf,
    inputSummary: text || (input.assetPlaceholder ? '已上传素材' : ''),
    sourceBlueprint: bp.template_id,
    nextActionHint: (gl && gl.unlock_hint) || bp.unlock_hooks[0] || '分享解锁更多',
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
  // 仅返回 base64 且超限：本地无法保存/渲染。绝不静默丢图还标 realGeneration=true，
  // 否则结果页是空白却显示"真实生成"。这种情况显式降级为 apiFailed/fallbackMode。
  const onlyLargeBase64 =
    !imageUrl &&
    !!r.image_base64 &&
    r.image_base64.length > MAX_BASE64_LEN
  if (onlyLargeBase64) {
    return buildApiFailedFallback(
      bp,
      input,
      '真实生成成功但图片体积过大，无法本地保存/渲染（仅返回超大 base64、无图片 URL）',
    )
  }
  if (!imageUrl && r.image_base64 && r.image_base64.length <= MAX_BASE64_LEN) {
    imageBase64 = r.image_base64
  }
  // 真实结果以后端 preview_type 为准（image / avatar / stickerPack / petVideo）。
  const previewType = (resp.preview_type || r.preview_type || bp.preview_type) as PreviewType
  const gl = bp.growth_loop
  // base64-only（有可渲染 base64 但无可保存 URL）：图能显示、realGeneration 仍为 true，
  // 但没有稳定文件可存相册，导出能力如实降级（finding #1，方案 B），不留假承诺。
  const isBase64Only = !imageUrl && !!imageBase64
  // 以 mock_example 的 preview_data 为题材身份底座（avatar 的 note/styles、sticker 的
  // theme/stickers/count、petVideo 的 line/duration），再叠加真实图片字段，
  // 让题材分支的可读字段 + 真实生成图同时可见，而不是丢掉题材身份只剩一张图。
  const identityData = { ...(example.preview_data || {}) }
  const promptText = r.prompt || prompt
  if (promptText) {
    if ('note' in identityData) identityData.note = `风格关键词：${promptText}`
    else if ('theme' in identityData) identityData.theme = promptText
    else if ('line' in identityData) identityData.line = promptText
  }
  const previewData = {
    ...identityData,
    image: imageUrl,
    image_base64: imageBase64,
    prompt: promptText,
    caption: r.caption || '',
    // pet-talk 等视频预留：后端 video_supported=false 时如实标注
    videoSupported: resp.video_supported !== false ? undefined : false,
  }
  return {
    id: genId(),
    createdAt: Date.now(),
    template: tpl,
    title: r.title || example.title,
    previewType,
    previewData,
    shareTitle: (gl && gl.share_title) || example.share_title || bp.share_hooks[0] || '看看我生成的结果',
    shareCopy: (gl && gl.share_copy) || example.share_copy || bp.share_hooks[1] || bp.share_hooks[0] || '',
    unlockHint: (gl && gl.unlock_hint) || example.unlock_hint || bp.unlock_hooks[0] || '分享解锁高清无水印结果',
    // 水印初始态来自事实源 has_watermark（finding #6）。
    watermarkEnabled: gl ? gl.has_watermark !== false : true,
    // 核心模板真实链路成功：如实标记 real_generation / template_api。
    templateStatus: bp.template_status || 'core_runnable',
    generationBackend: bp.generation_backend || 'template_api',
    realGeneration: true,
    fallbackMode: false,
    boundaryNote: bp.boundary_note,
    // 结构化传播闭环字段（P0-2）：真实链路成功时 capability_mode 仍取自事实源（核心模板为 real）。
    ...growthFields(bp),
    // base64-only：图可渲染但无稳定文件可存相册，导出/下载如实降级（finding #1）。
    ...(isBase64Only ? downgradeExportForBase64Only(bp) : {}),
    inputSummary: prompt,
    sourceBlueprint: tpl,
    nextActionHint: (gl && gl.unlock_hint) || bp.unlock_hooks[0] || '分享解锁更多',
  }
}

// 核心模板真实 API 失败时的降级预览：显式标记 apiFailed + fallbackMode，
// 绝不静默伪装成真实生成成功（spec P0-1 收口要求）。
function buildApiFailedFallback(
  bp: Blueprint,
  input: GenerateInput,
  reason: string,
): GeneratedResult {
  const base = buildFromBlueprint(bp, input)
  base.previewData = {
    ...(base.previewData || {}),
    api_failed: true,
    fallback_note: '真实生成暂时不可用，已临时回退本地预览',
  }
  // 真实链路失败：清掉 mock_example 里可能带的占位 image/image_base64，
  // 否则结果会残留一张"占位图"被前端当成真实生成图展示（hasRealImage 误判）。
  delete (base.previewData as any).image
  delete (base.previewData as any).image_base64
  return {
    id: genId(),
    createdAt: Date.now(),
    ...base,
    // 真实链路失败：不冒充真实生成成功。capability 口径整体降级（含 growthLoop 对象 +
    // 扁平 capabilityMode/exportSupported/downloadSupported），杜绝口径冲突（finding #2）。
    ...downgradeGrowthLoopForFallback(bp, reason),
    realGeneration: false,
    fallbackMode: true,
    apiFailed: true,
    fallbackReason: reason,
    qaHint: '真实生成失败，当前展示为本地预览（apiFailed）',
  }
}

// 诚实预览型 mock（funny-video / blessing-video 等暂无真实视频生成的模板）。
// 明确标注 honest_fallback，前端/QA/产物口径一致，不伪装成已完成真实生成。
function buildHonestPreview(bp: Blueprint, input: GenerateInput): GeneratedResult {
  const base = buildFromBlueprint(bp, input)
  base.previewData = {
    ...(base.previewData || {}),
    honest_fallback: true,
    fallback_note: bp.boundary_note || '当前为预览型结果，真实视频生成为后续能力边界',
  }
  return {
    id: genId(),
    createdAt: Date.now(),
    ...base,
    // 诚实边界型：明确 honest_preview / honest_fallback，不伪装真实视频生成。
    templateStatus: 'honest_preview',
    generationBackend: 'honest_fallback',
    realGeneration: false,
    fallbackMode: true,
    boundaryNote: bp.boundary_note || '真实视频生成是后续能力边界',
    qaHint: 'honest fallback / preview mode',
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

// 正式生成入口。按模板能力状态执行：
// - 诚实边界型（funny/blessing）：永远走 honest fallback / preview mode，绝不调真实接口；
// - 核心模板（ai-image/avatar/sticker/pet-talk）：api 模式优先走后端真实链路，
//   失败时降级为本地预览但显式标记 apiFailed + fallbackMode，不静默伪装成功；
// - 其余 / 未配置：本地 mock。
export async function mockGenerate(input: GenerateInput): Promise<GeneratedResult> {
  const bp = loadBlueprint()

  // 诚实边界型模板（funny-video / blessing-video）：无论何种模式都走诚实预览，
  // 不调用真实接口，也不冒充真实视频生成。
  if (PREVIEW_ONLY_TEMPLATES.indexOf(bp.template_id) !== -1) {
    const preview = buildHonestPreview(bp, input)
    saveResult(preview)
    return preview
  }

  // 核心模板 api 模式：优先走后端真实链路。真实调用失败时降级为本地预览，
  // 但显式标记 apiFailed + fallbackMode + fallbackReason，不静默伪装真实成功。
  if (GENERATION_MODE === 'api' && API_TEMPLATES.indexOf(bp.template_id) !== -1) {
    try {
      const real = await callRealApi(bp, input)
      if (real) {
        saveResult(real)
        return real
      }
    } catch (e: any) {
      const reason = (e && e.message) || '真实生成调用失败'
      const degraded = buildApiFailedFallback(bp, input, reason)
      saveResult(degraded)
      return degraded
    }
  }

  // 本地 mock：模拟一点生成耗时
  await new Promise((r) => setTimeout(r, 600))

  // 核心模板（事实源 real_generation=true）但当前构建未配置真实 API：本次结果并非真实生成，
  // 必须降级为本地预览态，不得显示 real / 高清导出（finding #2）。
  if (API_TEMPLATES.indexOf(bp.template_id) !== -1 && bp.real_generation === true) {
    const local = buildLocalPreviewFallback(bp, input)
    saveResult(local)
    return local
  }

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

// 分享解锁（本地 mock）：按 growth_loop 的去水印能力决定能否去水印。
// 只有 removeWatermarkSupported 时才真正去水印；否则保留水印、仅标记已分享解锁，
// 不假装去掉一个事实源上「不支持去水印」的水印。
export function unlockResult(id: string): GeneratedResult | null {
  const r = loadResult(id)
  if (!r) return null
  // 去水印能力来自结构化事实源（growthLoop.remove_watermark_supported）。
  const removeSupported = r.removeWatermarkSupported !== false
  if (removeSupported) {
    r.watermarkEnabled = false
  }
  r.unlocked = true
  saveResult(r)
  return r
}

// ===== 激励广告（rewarded video ad）下载门槛（P0-2）=====
// 用户预览结果后，要下载高清无水印图片/视频，必须先看完激励广告。
// 广告由开发者配置 adUnitId（config/ads.ts，codegen 注入）；未配置时诚实提示，不假装完成。

// 该结果是否需要激励广告解锁下载（gate.enabled + rewarded_ad，且尚未解锁）。
export function isRewardedAdRequired(result: GeneratedResult): boolean {
  const gate = result.downloadGate
  if (!gate || !gate.enabled || gate.gate_type !== 'rewarded_ad') return false
  return result.adUnlocked !== true
}

// 看完广告后落库：adUnlocked + downloadUnlocked=true；若事实源支持去水印则去水印。
export function markAdUnlocked(id: string): GeneratedResult | null {
  const r = loadResult(id)
  if (!r) return null
  r.adUnlocked = true
  r.downloadUnlocked = true
  r.unlocked = true
  const gate = r.downloadGate
  const requiresRemove = !!(gate && gate.required_for && gate.required_for.indexOf('remove_watermark') !== -1)
  // 去水印仅当事实源支持，且 gate 要求 remove_watermark（看完广告才去）。
  let removed = false
  if (requiresRemove && r.removeWatermarkSupported !== false) {
    r.watermarkEnabled = false
    removed = true
  }
  saveResult(r)
  // 漏斗：解锁成功；若同时去水印再记一条 watermark_removed。
  trackGrowthEvent('download_unlocked', growthContextFromResult(r))
  if (removed) trackGrowthEvent('watermark_removed', growthContextFromResult(r))
  return r
}

// 兼容别名：看完激励广告后解锁下载（语义同 markAdUnlocked）。
export function unlockAfterRewardedAd(id: string): GeneratedResult | null {
  return markAdUnlocked(id)
}

// rewarded video ad 包装：兼容 wx / uni，可注入（单测不依赖真实 SDK）。
export interface RewardedAdLike {
  load: () => Promise<void> | void
  show: () => Promise<void> | void
  onClose: (cb: (res: { isEnded: boolean }) => void) => void
  onError: (cb: (err: any) => void) => void
}
export type RewardedAdFactory = (adUnitId: string) => RewardedAdLike | null

// 默认工厂：用平台 createRewardedVideoAd（wx 优先，回退 uni）。单测会注入 mock 工厂。
function defaultRewardedAdFactory(adUnitId: string): RewardedAdLike | null {
  const api: any = typeof wx !== 'undefined' ? wx : (typeof uni !== 'undefined' ? uni : null)
  if (!api || typeof api.createRewardedVideoAd !== 'function') return null
  const ad = api.createRewardedVideoAd({ adUnitId })
  return {
    load: () => ad.load && ad.load(),
    show: () => ad.show && ad.show(),
    onClose: (cb) => ad.onClose && ad.onClose(cb),
    onError: (cb) => ad.onError && ad.onError(cb),
  }
}

let _rewardedAdFactory: RewardedAdFactory = defaultRewardedAdFactory
// 测试注入点：替换 rewarded ad 工厂（生产代码不调用）。
export function __setRewardedAdFactory(f: RewardedAdFactory): void {
  _rewardedAdFactory = f
}

export type RewardedAdUnlockReason = 'not_configured' | 'ad_error' | 'closed_early' | 'no_result'

// 请求激励广告解锁下载。规则：
// - adUnitId 为空 / 广告未启用：ok=false reason='not_configured'（诚实提示，不假装）；
// - 找不到结果：ok=false reason='no_result'；
// - 广告看完 isEnded=true：markAdUnlocked，ok=true；
// - 中途关闭 isEnded=false：ok=false reason='closed_early'，不解锁；
// - load/show/onError 报错：ok=false reason='ad_error'，不解锁。
export async function requestRewardedAdUnlock(resultId: string): Promise<{
  ok: boolean
  reason?: RewardedAdUnlockReason
  result?: GeneratedResult
}> {
  const current = loadResult(resultId)
  if (!current) return { ok: false, reason: 'no_result' }

  const gate = current.downloadGate
  const adUnitId = (gate && gate.ad_unit_id) || REWARDED_AD_UNIT_ID || ''
  const ctx = growthContextFromResult(current)
  // 漏斗：请求拉广告。
  trackGrowthEvent('rewarded_ad_request', ctx)
  // 广告位未配置 / 全局未启用：诚实失败，不解锁。
  if (!REWARDED_AD_ENABLED || !adUnitId) {
    trackGrowthEvent('rewarded_ad_not_configured', { ...ctx, reason: 'not_configured' })
    return { ok: false, reason: 'not_configured', result: current }
  }

  const ad = _rewardedAdFactory(adUnitId)
  if (!ad) {
    trackGrowthEvent('rewarded_ad_not_configured', { ...ctx, reason: 'no_ad_factory' })
    return { ok: false, reason: 'not_configured', result: current }
  }

  return new Promise((resolve) => {
    let settled = false
    const done = (r: { ok: boolean; reason?: RewardedAdUnlockReason; result?: GeneratedResult }) => {
      if (settled) return
      settled = true
      resolve(r)
    }
    try {
      ad.onError(() => {
        trackGrowthEvent('rewarded_ad_show_error', { ...ctx, reason: 'ad_error' })
        done({ ok: false, reason: 'ad_error', result: loadResult(resultId) || current })
      })
      ad.onClose((res) => {
        // 看完整条广告（isEnded=true）才解锁；中途关闭不解锁。
        if (res && res.isEnded) {
          // 漏斗：完播 -> 解锁（markAdUnlocked 内部记 download_unlocked / watermark_removed）。
          trackGrowthEvent('rewarded_ad_completed', ctx)
          const updated = markAdUnlocked(resultId)
          done({ ok: true, result: updated || current })
        } else {
          trackGrowthEvent('rewarded_ad_closed_early', { ...ctx, reason: 'closed_early' })
          done({ ok: false, reason: 'closed_early', result: loadResult(resultId) || current })
        }
      })
      Promise.resolve(ad.load())
        .then(() => ad.show())
        .catch(() => {
          trackGrowthEvent('rewarded_ad_load_error', { ...ctx, reason: 'ad_error' })
          done({ ok: false, reason: 'ad_error', result: loadResult(resultId) || current })
        })
    } catch (e) {
      trackGrowthEvent('rewarded_ad_show_error', { ...ctx, reason: 'ad_error' })
      done({ ok: false, reason: 'ad_error', result: loadResult(resultId) || current })
    }
  })
}
