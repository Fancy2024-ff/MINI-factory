// 统一生成服务（本地 mock 闭环，预留真实 API 切换点）。
//
// 设计：
// - mockGenerate 根据 SELECTED_TEMPLATE 返回不同题材的 GeneratedResult。
// - 不写真实 key、不硬编码真实服务；GENERATION_ENDPOINT 为空时走本地 mock，
//   后续把它指向真实后端即可切换（callRealApi 预留）。
// - 结果存到本地缓存（uni.setStorageSync），result 页按 id 读取。

import { SELECTED_TEMPLATE } from '../config/template'

export type PreviewType =
  | 'avatar'
  | 'stickerPack'
  | 'petVideo'
  | 'funnyStoryboard'
  | 'blessingCard'
  | 'image'
  | 'text'

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
}

export interface GenerateInput {
  text?: string
  assetPlaceholder?: string
  extra?: Record<string, any>
}

// 预留：真实后端地址。留空 = 走本地 mock。切真实服务时填这里 + 实现 callRealApi。
const GENERATION_ENDPOINT = ''

const STORAGE_PREFIX = 'gen-result:'

function genId(): string {
  return 'g-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e6).toString(36)
}

// 题材 -> mock 结果形态。每类返回不同 previewType / previewData / 文案。
function buildMock(template: string, input: GenerateInput): Omit<GeneratedResult, 'id' | 'createdAt'> {
  const text = (input.text || '').trim()
  switch (template) {
    case 'avatar-viral':
      return {
        template,
        title: '你的专属 AI 头像',
        previewType: 'avatar',
        previewData: {
          styles: ['赛博朋克', '日系动漫', '商务证件', '油画风'],
          cover: 'avatar-preview-placeholder',
          note: text ? `风格关键词：${text}` : '默认多风格头像',
        },
        shareTitle: '我用 AI 生成了专属头像，快来看！',
        shareCopy: '一键生成多风格 AI 头像，分享解锁高清无水印版',
        unlockHint: '分享给好友解锁高清无水印 + 解锁全部风格',
        watermarkEnabled: true,
      }
    case 'sticker-viral':
      return {
        template,
        title: '你的专属表情包',
        previewType: 'stickerPack',
        previewData: {
          theme: text || '默认主题',
          stickers: ['开心', '加油', '无语', '比心', '震惊', '收到'],
          count: 6,
        },
        shareTitle: '我做了一套搞怪表情包！',
        shareCopy: '一句话生成整套表情包，分享到群聊解锁更多表情',
        unlockHint: '分享到群聊解锁更多表情 + 去水印导出',
        watermarkEnabled: true,
      }
    case 'pet-talk-viral':
      return {
        template,
        title: '会说话的宠物视频',
        previewType: 'petVideo',
        previewData: {
          line: text || '主人，该喂饭啦！',
          duration: 8,
          poster: 'pet-video-poster-placeholder',
        },
        shareTitle: '我家宠物开口说话了！',
        shareCopy: '上传宠物照 + 一句台词，生成会说话的宠物视频',
        unlockHint: '分享到朋友圈解锁高清视频 + 去水印',
        watermarkEnabled: true,
      }
    case 'funny-video-viral':
      return {
        template,
        title: '15 秒搞笑短视频脚本',
        previewType: 'funnyStoryboard',
        previewData: {
          topic: text || '打工人的一天',
          shots: [
            { t: '0-3s', desc: '夸张开场，抛出反差设定' },
            { t: '3-9s', desc: '冲突升级，密集笑点' },
            { t: '9-15s', desc: '反转结尾 + 行动号召' },
          ],
        },
        shareTitle: '这个搞笑脚本我能笑一年',
        shareCopy: '输入主题秒出分镜脚本，发起接龙挑战一起拍',
        unlockHint: '分享发起挑战解锁更多分镜模板 + 去水印',
        watermarkEnabled: true,
      }
    case 'blessing-video-viral':
      return {
        template,
        title: '专属祝福贺卡',
        previewType: 'blessingCard',
        previewData: {
          to: input.extra?.to || '亲爱的朋友',
          festival: input.extra?.festival || '新年',
          message: text || '愿你新年快乐，万事如意！',
          theme: 'festival-card-placeholder',
        },
        shareTitle: '送你一张专属祝福贺卡',
        shareCopy: '填名字和祝福语，一键生成祝福贺卡群发好友',
        unlockHint: '分享/群发解锁高清贺卡 + 去水印',
        watermarkEnabled: true,
      }
    default:
      // base / ai-tool / 其他：通用文本结果，仍保留传播闭环
      return {
        template,
        title: '生成结果',
        previewType: 'text',
        previewData: { text: text || '这是一段示例生成结果。' },
        shareTitle: '看看我用它生成的结果',
        shareCopy: '一键生成，分享解锁完整高清结果',
        unlockHint: '分享解锁高清无水印结果 + 解锁更多模板',
        watermarkEnabled: true,
      }
  }
}

// 预留真实 API 调用（当前未启用）。返回 null 表示回退本地 mock。
async function callRealApi(_input: GenerateInput): Promise<GeneratedResult | null> {
  // 后续接真实后端时在此实现 uni.request(GENERATION_ENDPOINT, ...)。
  return null
}

export async function mockGenerate(input: GenerateInput): Promise<GeneratedResult> {
  if (GENERATION_ENDPOINT) {
    const real = await callRealApi(input)
    if (real) {
      saveResult(real)
      return real
    }
  }
  // 本地 mock：模拟一点生成耗时
  await new Promise((r) => setTimeout(r, 600))
  const result: GeneratedResult = {
    id: genId(),
    createdAt: Date.now(),
    ...buildMock(SELECTED_TEMPLATE, input),
  }
  saveResult(result)
  return result
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
