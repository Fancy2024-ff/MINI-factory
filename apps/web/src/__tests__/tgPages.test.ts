// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import TgHome from '../tg/TgHome.vue'
import AiImagePage from '../tg/AiImagePage.vue'
import AvatarPage from '../tg/AvatarPage.vue'
import StickerPage from '../tg/StickerPage.vue'
import PetTalkPage from '../tg/PetTalkPage.vue'

beforeEach(() => {
  // 默认无 Telegram WebApp 对象（普通浏览器场景）
  delete (window as any).Telegram
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('TgHome', () => {
  it('renders ai-image entry as 已开放 and blessing as 即将开放', () => {
    const w = mount(TgHome)
    const text = w.text()
    expect(text).toContain('AI 图片生成')
    expect(text).toContain('已开放')
    expect(text).toContain('即将开放')  // blessing 仍未开放
  })

  it('shows avatar/sticker/pet-talk entries as opened (新上线)', () => {
    const w = mount(TgHome)
    const text = w.text()
    expect(text).toContain('AI 头像')
    expect(text).toContain('表情包工厂')
    expect(text).toContain('宠物说话')
    expect(text).toContain('新上线')
    // 四张可点击的已开放卡片（ai-image + avatar + sticker + pet-talk）
    expect(w.findAll('.card-open').length).toBe(4)
  })

  it('emits navigate to /tg/ai-image when first open card clicked', async () => {
    const w = mount(TgHome)
    await w.find('.card-open').trigger('click')
    expect(w.emitted('navigate')?.[0]).toEqual(['/tg/ai-image'])
  })

  it('emits navigate to /tg/avatar when avatar card clicked', async () => {
    const w = mount(TgHome)
    const cards = w.findAll('.card-open')
    await cards[1].trigger('click')
    expect(w.emitted('navigate')?.[0]).toEqual(['/tg/avatar'])
  })

  it('emits navigate to /tg/sticker and /tg/pet-talk for the new cards', async () => {
    const w = mount(TgHome)
    const cards = w.findAll('.card-open')
    await cards[2].trigger('click')
    expect(w.emitted('navigate')?.[0]).toEqual(['/tg/sticker'])
    const w2 = mount(TgHome)
    const cards2 = w2.findAll('.card-open')
    await cards2[3].trigger('click')
    expect(w2.emitted('navigate')?.[0]).toEqual(['/tg/pet-talk'])
  })
})

describe('AiImagePage', () => {
  it('renders the initial form (prompt + generate)', () => {
    const w = mount(AiImagePage)
    expect(w.find('.prompt-input').exists()).toBe(true)
    expect(w.find('.generate-btn').exists()).toBe(true)
    expect(w.find('.result').exists()).toBe(false)
  })

  it('does NOT crash without window.Telegram', () => {
    expect((window as any).Telegram).toBeUndefined()
    const w = mount(AiImagePage)
    expect(w.exists()).toBe(true)
  })

  it('shows the image after a successful generation (base64 -> data URI)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        result: { preview_type: 'image', image_base64: 'QUJD', prompt: 'cat', title: 'AI 图片生成' },
      }),
    } as any))

    const w = mount(AiImagePage)
    await w.find('.prompt-input').setValue('一只猫')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    const img = w.find('.result-img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('data:image/jpeg;base64,QUJD')
  })

  it('shows a friendly error when generation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: false,
        error: { code: 'IMAGE_GENERATION_PROVIDER_FAILED', message: '图片生成失败，请稍后再试', retryable: true },
      }),
    } as any))

    const w = mount(AiImagePage)
    await w.find('.prompt-input').setValue('一只猫')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    expect(w.find('.error-box').exists()).toBe(true)
    expect(w.text()).toContain('图片生成失败')
    expect(w.find('.result-img').exists()).toBe(false)
  })
})

describe('AvatarPage', () => {
  it('renders the avatar form (prompt + style/mood/scene chips)', () => {
    const w = mount(AvatarPage)
    expect(w.find('.prompt-input').exists()).toBe(true)
    expect(w.find('.generate-btn').exists()).toBe(true)
    // 风格/气质/场景三组 chips
    expect(w.text()).toContain('风格')
    expect(w.text()).toContain('气质')
    expect(w.text()).toContain('场景')
    expect(w.find('.result').exists()).toBe(false)
  })

  it('does NOT crash without window.Telegram', () => {
    expect((window as any).Telegram).toBeUndefined()
    const w = mount(AvatarPage)
    expect(w.exists()).toBe(true)
  })

  it('shows the avatar image after a successful generation (template endpoint)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        template_id: 'avatar-viral',
        preview_type: 'avatar',
        result: { image_base64: 'QUJD', prompt: '短发女生', title: 'AI 头像已生成' },
      }),
    } as any))

    const w = mount(AvatarPage)
    await w.find('.prompt-input').setValue('短发女生')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    const img = w.find('.result-img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('data:image/jpeg;base64,QUJD')
  })

  it('shows a friendly error when avatar generation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: false,
        error: { code: 'IMAGE_GENERATION_PROVIDER_FAILED', message: '生成失败，请稍后再试', retryable: true },
      }),
    } as any))

    const w = mount(AvatarPage)
    await w.find('.prompt-input').setValue('短发女生')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    expect(w.find('.error-box').exists()).toBe(true)
    expect(w.text()).toContain('生成失败')
    expect(w.find('.result-img').exists()).toBe(false)
  })
})

describe('StickerPage', () => {
  it('renders the sticker form (prompt + mood chips)', () => {
    const w = mount(StickerPage)
    expect(w.find('.prompt-input').exists()).toBe(true)
    expect(w.find('.generate-btn').exists()).toBe(true)
    expect(w.text()).toContain('情绪倾向')
    expect(w.find('.result').exists()).toBe(false)
  })

  it('does NOT crash without window.Telegram', () => {
    const w = mount(StickerPage)
    expect(w.exists()).toBe(true)
  })

  it('shows the sticker image after a successful generation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        template_id: 'sticker-viral',
        preview_type: 'stickerPack',
        result: { image_base64: 'QUJD', prompt: '打工人', title: '表情包已生成' },
      }),
    } as any))

    const w = mount(StickerPage)
    await w.find('.prompt-input').setValue('打工人')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    const img = w.find('.result-img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('data:image/jpeg;base64,QUJD')
  })
})

describe('PetTalkPage', () => {
  it('renders the form and an honest video-not-supported notice', () => {
    const w = mount(PetTalkPage)
    expect(w.find('.prompt-input').exists()).toBe(true)
    expect(w.find('.generate-btn').exists()).toBe(true)
    // 诚实边界：页面必须明确标注「静态预览 / 视频流程预留」，不虚假承诺
    expect(w.find('.notice').exists()).toBe(true)
    expect(w.text()).toContain('静态预览')
    expect(w.text()).toContain('预留')
  })

  it('does NOT crash without window.Telegram', () => {
    const w = mount(PetTalkPage)
    expect(w.exists()).toBe(true)
  })

  it('shows static preview with a 预留 badge after generation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        template_id: 'pet-talk-viral',
        preview_type: 'petVideo',
        video_supported: false,
        result: { image_base64: 'QUJD', prompt: '主人该喂饭啦', title: '宠物说话预览（视频生成为流程预留）' },
      }),
    } as any))

    const w = mount(PetTalkPage)
    await w.find('.prompt-input').setValue('主人该喂饭啦')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    const img = w.find('.result-img')
    expect(img.exists()).toBe(true)
    expect(w.find('.preview-badge').exists()).toBe(true)
    expect(w.text()).toContain('视频生成流程预留')
  })
})
