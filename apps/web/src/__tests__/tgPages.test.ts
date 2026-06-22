// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import TgHome from '../tg/TgHome.vue'
import AiImagePage from '../tg/AiImagePage.vue'
import AvatarPage from '../tg/AvatarPage.vue'

beforeEach(() => {
  // 默认无 Telegram WebApp 对象（普通浏览器场景）
  delete (window as any).Telegram
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('TgHome', () => {
  it('renders ai-image entry as 已开放 and others as 即将开放', () => {
    const w = mount(TgHome)
    const text = w.text()
    expect(text).toContain('AI 图片生成')
    expect(text).toContain('已开放')
    expect(text).toContain('即将开放')
  })

  it('shows avatar entry as opened (新上线), not 即将开放', () => {
    const w = mount(TgHome)
    expect(w.text()).toContain('AI 头像')
    expect(w.text()).toContain('新上线')
    // 应有两张可点击的已开放卡片（ai-image + avatar）
    expect(w.findAll('.card-open').length).toBe(2)
  })

  it('emits navigate to /tg/ai-image when open card clicked', async () => {
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
