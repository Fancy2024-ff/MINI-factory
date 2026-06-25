// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import TgHome from '../tg/TgHome.vue'
import AiImagePage from '../tg/AiImagePage.vue'
import AvatarPage from '../tg/AvatarPage.vue'
import StickerPage from '../tg/StickerPage.vue'
import PetTalkPage from '../tg/PetTalkPage.vue'
import BgRemovePage from '../tg/BgRemovePage.vue'

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
    expect(text).toContain('背景去除')
    expect(text).toContain('新上线')
    // 五张可点击的已开放卡片（ai-image + avatar + sticker + pet-talk + bg-remove）
    expect(w.findAll('.card-open').length).toBe(5)
  })

  it('emits navigate to /tg/bg-remove when background-removal card clicked', async () => {
    const w = mount(TgHome)
    const cards = w.findAll('.card-open')
    await cards[4].trigger('click')
    expect(w.emitted('navigate')?.[0]).toEqual(['/tg/bg-remove'])
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

  it('keeps showing the loading spinner (NOT an error) while a retryable failure is retried, then shows the image once it succeeds', async () => {
    // provider 偶发失败（retryable）：前两次失败，第三次成功。
    // 期望：全程不出现 error-box / 失败文案，最终出图。
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: false,
          error: { code: 'IMAGE_GENERATION_PROVIDER_FAILED', message: '图片生成失败，请稍后再试', retryable: true },
        }),
      } as any)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: false,
          error: { code: 'IMAGE_GENERATION_PROVIDER_FAILED', message: '图片生成失败，请稍后再试', retryable: true },
        }),
      } as any)
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          ok: true,
          result: { preview_type: 'image', image_base64: 'QUJD', prompt: 'cat', title: 'AI 图片生成' },
        }),
      } as any)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const w = mount(AiImagePage)
    await w.find('.prompt-input').setValue('一只猫')
    await w.find('.generate-btn').trigger('click')

    // 第一次失败后：仍在 loading，绝不显示错误。
    await vi.advanceTimersByTimeAsync(0)
    await nextTick()
    expect(w.find('.loading').exists()).toBe(true)
    expect(w.find('.error-box').exists()).toBe(false)
    expect(w.text()).not.toContain('图片生成失败')

    // 推进退避计时器，让后台重试跑到成功。
    await vi.advanceTimersByTimeAsync(10000)
    await nextTick()

    expect(w.find('.error-box').exists()).toBe(false)
    const img = w.find('.result-img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('data:image/jpeg;base64,QUJD')
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3)
    vi.useRealTimers()
  })

  it('shows a friendly error only for a non-retryable (config) failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: false,
        error: { code: 'IMAGE_GENERATION_NOT_CONFIGURED', message: '服务暂时不可用', retryable: false },
      }),
    } as any))

    const w = mount(AiImagePage)
    await w.find('.prompt-input').setValue('一只猫')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    expect(w.find('.error-box').exists()).toBe(true)
    expect(w.find('.result-img').exists()).toBe(false)
  })

  it('does NOT show "Image result is missing" — MALFORMED_RESPONSE (retryable:false) is retried silently', async () => {
    // 复现截图 bug：后端把 provider 偶发空图标成 MALFORMED_RESPONSE + retryable:false，
    // 前端不能信任该字段，应继续静默重试，绝不把 "Image result is missing" 显示给用户。
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: false,
          error: { code: 'IMAGE_GENERATION_MALFORMED_RESPONSE', message: 'Image result is missing.', retryable: false },
        }),
      } as any)
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          ok: true,
          result: { preview_type: 'image', image_base64: 'QUJD', prompt: 'cat', title: 'AI 图片生成' },
        }),
      } as any)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const w = mount(AiImagePage)
    await w.find('.prompt-input').setValue('一只猫')
    await w.find('.generate-btn').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await nextTick()
    // 第一次 MALFORMED 后：仍转圈，不显示该英文报错。
    expect(w.find('.loading').exists()).toBe(true)
    expect(w.find('.error-box').exists()).toBe(false)
    expect(w.text()).not.toContain('Image result is missing')

    await vi.advanceTimersByTimeAsync(10000)
    await nextTick()
    expect(w.find('.error-box').exists()).toBe(false)
    expect(w.find('.result-img').exists()).toBe(true)
    vi.useRealTimers()
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

  it('does NOT show an error on a retryable avatar failure — stays loading and retries silently', async () => {
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

    // 可重试失败：保持转圈，绝不显示错误或失败文案。
    expect(w.find('.loading').exists()).toBe(true)
    expect(w.find('.error-box').exists()).toBe(false)
    expect(w.text()).not.toContain('生成失败')
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

  it('slices the sheet into a clickable 9-cell grid and a cell click opens the ad gate', async () => {
    // 桩 Image（立即 onload）+ canvas（getContext/toDataURL），让 sliceGrid 切出 9 张。
    class FakeImage {
      crossOrigin = ''
      naturalWidth = 300
      naturalHeight = 300
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      set src(_v: string) { setTimeout(() => this.onload?.(), 0) }
    }
    vi.stubGlobal('Image', FakeImage as any)
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'canvas') {
        return { width: 0, height: 0,
          getContext: () => ({ drawImage: () => {} }),
          toDataURL: () => 'data:image/png;base64,CELL' } as any
      }
      return origCreate(tag)
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true, template_id: 'sticker-viral', preview_type: 'stickerPack',
        result: { image_base64: 'QUJD', prompt: '打工人', title: '表情包已生成' },
      }),
    } as any))

    const w = mount(StickerPage)
    await w.find('.prompt-input').setValue('打工人')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0)) // 生成完成
    await nextTick()
    await new Promise((r) => setTimeout(r, 0)) // sliceGrid 完成
    await nextTick()

    const cellItems = w.findAll('.cell-item')
    expect(cellItems.length).toBe(9)
    // 有「全部下载」按钮
    expect(w.text()).toContain('全部下载')
    // 点单个表情 → 弹出看广告遮罩（下载闸门）
    await cellItems[0].trigger('click')
    expect(w.find('.ad-overlay').exists()).toBe(true)

    vi.unstubAllGlobals()
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

describe('BgRemovePage', () => {
  function setFile(w: any) {
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' })
    // jsdom 没有真实 file input；直接设组件内部 sourceFile 触发可生成态。
    ;(w.vm as any).sourceFile = blob
    ;(w.vm as any).sourcePreview = 'blob:fake'
  }

  it('renders the uploader form', () => {
    const w = mount(BgRemovePage)
    expect(w.find('.uploader').exists()).toBe(true)
    expect(w.text()).toContain('背景去除')
    expect(w.find('.result').exists()).toBe(false)
  })

  it('shows the cut-out image after a successful background removal', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        result: { preview_type: 'image', image_base64: 'QUJD', title: '背景去除' },
      }),
    } as any))

    const w = mount(BgRemovePage)
    setFile(w)
    await nextTick()
    await (w.vm as any).onRemove()
    await nextTick()

    const img = w.find('.result-img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('data:image/jpeg;base64,QUJD')
  })

  it('retries silently on a retryable edit failure — no error shown', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: false, error: { code: 'IMAGE_GENERATION_MALFORMED_RESPONSE', message: 'Image result is missing.', retryable: false } }),
      } as any)
      .mockResolvedValue({
        ok: true,
        json: async () => ({ ok: true, result: { preview_type: 'image', image_base64: 'QUJD', title: '背景去除' } }),
      } as any)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    const w = mount(BgRemovePage)
    setFile(w)
    const p = (w.vm as any).onRemove()
    await vi.advanceTimersByTimeAsync(0)
    await nextTick()
    expect(w.find('.loading').exists()).toBe(true)
    expect(w.text()).not.toContain('Image result is missing')

    await vi.advanceTimersByTimeAsync(10000)
    await p
    await nextTick()
    expect(w.find('.result-img').exists()).toBe(true)
    vi.useRealTimers()
  })
})

describe('下载 + 看广告解锁（出图页共用）', () => {
  // 渲染出结果态：先 mock 成功生成，再点生成。
  async function mountWithResult(Page: any, fillForm: (w: any) => Promise<void>) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        result: { preview_type: 'image', image_base64: 'QUJD', prompt: 'x', title: 't' },
      }),
    } as any))
    const w = mount(Page)
    await fillForm(w)
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
    return w
  }

  it('AiImagePage 结果态有下载按钮，点击弹出看广告遮罩', async () => {
    const w = await mountWithResult(AiImagePage, async (w) => {
      await w.find('.prompt-input').setValue('一只猫')
    })
    expect(w.find('.result-img').exists()).toBe(true)
    const dl = w.findAll('.act').find((b: any) => b.text().includes('下载'))
    expect(dl).toBeTruthy()
    expect(w.find('.ad-overlay').exists()).toBe(false)
    await dl!.trigger('click')
    await nextTick()
    // 看广告遮罩出现，倒计时未结束时「领取」禁用
    expect(w.find('.ad-overlay').exists()).toBe(true)
    expect(w.find('.ad-skip').attributes('disabled')).toBeDefined()
  })

  it('看完广告后点「领取并下载」触发下载并关闭遮罩', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, result: { preview_type: 'image', image_base64: 'QUJD', prompt: 'x', title: 't' } }),
    } as any))
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const w = mount(AiImagePage)
    await w.find('.prompt-input').setValue('一只猫')
    await w.find('.generate-btn').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await nextTick()

    const dl = w.findAll('.act').find((b: any) => b.text().includes('下载'))!
    await dl.trigger('click')
    await nextTick()
    // 推进 30s 广告倒计时
    await vi.advanceTimersByTimeAsync(30000)
    await nextTick()
    expect(w.find('.ad-skip').attributes('disabled')).toBeUndefined()
    await w.find('.ad-skip').trigger('click')
    await nextTick()
    expect(w.find('.ad-overlay').exists()).toBe(false)
    expect(clickSpy).toHaveBeenCalled()
    vi.useRealTimers()
  })
})

describe('downloadImage（环境自适应）', () => {
  it('Telegram 内 + 远程图：交给 openLink，不走 <a download>', async () => {
    const openLink = vi.fn()
    ;(window as any).Telegram = { WebApp: { openLink } }
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const { downloadImage } = await import('../tg/download')
    const r = await downloadImage('https://cdn.example.com/a.png', 'a.png')

    expect(r).toBe('opened')
    expect(openLink).toHaveBeenCalledWith('https://cdn.example.com/a.png')
    expect(clickSpy).not.toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('普通浏览器 + 远程图：先 fetch 成 blob 再用 <a download>', async () => {
    delete (window as any).Telegram
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x'], { type: 'image/png' }),
    } as any))
    ;(URL as any).createObjectURL = vi.fn(() => 'blob:fake')
    ;(URL as any).revokeObjectURL = vi.fn()
    const anchors: HTMLAnchorElement[] = []
    const orig = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = orig(tag) as any
      if (tag === 'a') { el.click = () => {}; anchors.push(el) }
      return el
    })

    const { downloadImage } = await import('../tg/download')
    const r = await downloadImage('https://cdn.example.com/a.png', 'a.png')

    expect(r).toBe('downloaded')
    expect(anchors[0].href).toContain('blob:')
    expect(anchors[0].download).toBe('a.png')
    vi.restoreAllMocks()
  })
})

describe('发送到聊天（Telegram 内）', () => {
  it('Telegram 内有 initData：结果区出现「发送到聊天」按钮；普通浏览器不出现', async () => {
    // 普通浏览器：无 Telegram，按钮不出现。
    delete (window as any).Telegram
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, template_id: 'avatar-viral', result: { image_base64: 'QUJD', prompt: 'p', title: 't' } }),
    } as any))
    let w = mount(AvatarPage)
    await w.find('.prompt-input').setValue('短发')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
    expect(w.text()).not.toContain('发送到聊天')

    // Telegram 内 + initData：按钮出现。
    ;(window as any).Telegram = { WebApp: { initData: 'auth_date=1&user=%7B%22id%22%3A1%7D&hash=x' } }
    w = mount(AvatarPage)
    await w.find('.prompt-input').setValue('短发')
    await w.find('.generate-btn').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
    expect(w.text()).toContain('发送到聊天')
  })

  it('解锁后点击「发送到聊天」调用 sendToChat 接口', async () => {
    vi.useFakeTimers()
    ;(window as any).Telegram = { WebApp: { initData: 'auth_date=1&user=%7B%22id%22%3A1%7D&hash=x' } }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, template_id: 'avatar-viral', result: { image_base64: 'QUJD', prompt: 'p', title: 't' } }),
    } as any)
    vi.stubGlobal('fetch', fetchMock)

    const w = mount(AvatarPage)
    await w.find('.prompt-input').setValue('短发')
    await w.find('.generate-btn').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await nextTick()

    const sendBtn = w.findAll('.act').find((b: any) => b.text().includes('发送到聊天'))!
    await sendBtn.trigger('click')          // 弹广告
    await nextTick()
    await vi.advanceTimersByTimeAsync(30000) // 看完广告
    await w.find('.ad-skip').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await nextTick()

    // 最后一次 fetch 应打到 send-to-chat。
    const calledSendToChat = fetchMock.mock.calls.some(
      (c: any[]) => typeof c[0] === 'string' && c[0].includes('/api/generation/send-to-chat'),
    )
    expect(calledSendToChat).toBe(true)
    vi.useRealTimers()
  })
})
