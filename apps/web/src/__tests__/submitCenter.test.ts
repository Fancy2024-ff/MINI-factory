// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SubmitCenterPanel from '../components/SubmitCenterPanel.vue'
import { api } from '../services/api'

function platformsAuth() {
  return {
    platforms: [
      { platform_id: 'wechat', platform_name: '微信小程序', configured: false, missing_config: ['appid'] },
      { platform_id: 'telegram', platform_name: 'Telegram Mini Apps', configured: true, missing_config: [] },
    ],
  }
}

function deployed() {
  return {
    items: [
      { route: '/tg/avatar', title: 'AI 头像', icon: '🧑‍🎨', source: 'builtin', platform: 'telegram',
        preview_url: 'https://x.pages.dev/tg/avatar', ad: { ad_enabled: true, ad_seconds: 30, video_url: '' } },
      { route: '/tg/sticker', title: '表情包工厂', icon: '😄', source: 'builtin', platform: 'telegram',
        preview_url: 'https://x.pages.dev/tg/sticker', ad: { ad_enabled: false, ad_seconds: 15, video_url: '' } },
    ],
    total: 2,
  }
}

beforeEach(() => {
  vi.spyOn(api, 'getPlatformAuth').mockResolvedValue(platformsAuth() as any)
})
afterEach(() => vi.restoreAllMocks())

describe('SubmitCenterPanel 两级页 + 广告管理', () => {
  it('一级页：平台卡片显示「已上架的小程序」入口与功能页数量', async () => {
    vi.spyOn(api, 'getDeployedApps').mockResolvedValue(deployed() as any)
    const w = mount(SubmitCenterPanel)
    await flushPromises()

    // 一级页不直接渲染 app-card，只有平台卡 + 入口
    expect(w.findAll('.app-card').length).toBe(0)
    const entries = w.findAll('.apps-entry')
    expect(entries.length).toBe(2)
    // telegram 入口显示 2 个功能页（wechat 0 个）
    expect(entries[0].text()).toContain('0 个功能页')   // wechat
    expect(entries[1].text()).toContain('2 个功能页')   // telegram
  })

  it('点 telegram 入口进二级页，显示该平台功能页', async () => {
    vi.spyOn(api, 'getDeployedApps').mockResolvedValue(deployed() as any)
    const w = mount(SubmitCenterPanel)
    await flushPromises()

    await w.findAll('.apps-entry')[1].trigger('click') // telegram
    await flushPromises()

    expect(w.find('.apps-detail').exists()).toBe(true)
    expect(w.findAll('.app-card').length).toBe(2)
    expect(w.find('.detail-title').text()).toContain('Telegram Mini Apps')
    expect(w.find('.app-preview iframe').attributes('src')).toBe('https://x.pages.dev/tg/avatar')
  })

  it('二级页返回一级页', async () => {
    vi.spyOn(api, 'getDeployedApps').mockResolvedValue(deployed() as any)
    const w = mount(SubmitCenterPanel)
    await flushPromises()
    await w.findAll('.apps-entry')[1].trigger('click')
    await flushPromises()
    await w.find('.detail-back').trigger('click')
    await flushPromises()
    expect(w.find('.apps-detail').exists()).toBe(false)
    expect(w.findAll('.apps-entry').length).toBe(2)
  })

  it('二级页切换上下架 + 保存，调用 saveAdConfig', async () => {
    vi.spyOn(api, 'getDeployedApps').mockResolvedValue(deployed() as any)
    const saveSpy = vi.spyOn(api, 'saveAdConfig').mockResolvedValue({
      ok: true, route: '/tg/avatar', ad: { ad_enabled: false, ad_seconds: 10 },
    } as any)
    const w = mount(SubmitCenterPanel)
    await flushPromises()
    await w.findAll('.apps-entry')[1].trigger('click')
    await flushPromises()

    const avatarCard = w.findAll('.app-card')[0]
    await avatarCard.find('.toggle').trigger('click') // 上架 -> 下架
    await avatarCard.find('.save-btn').trigger('click')
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledTimes(1)
    const [route, enabled] = saveSpy.mock.calls[0]
    expect(route).toBe('/tg/avatar')
    expect(enabled).toBe(false)
  })

  it('二级页上传广告视频调用 uploadAdVideo 并回填 video_url', async () => {
    vi.spyOn(api, 'getDeployedApps').mockResolvedValue(deployed() as any)
    const upSpy = vi.spyOn(api, 'uploadAdVideo').mockResolvedValue({
      ok: true, route: '/tg/avatar', video_url: '/api/tg/ad-video/tg-avatar.mp4',
    } as any)
    const w = mount(SubmitCenterPanel)
    await flushPromises()
    await w.findAll('.apps-entry')[1].trigger('click')
    await flushPromises()

    const fileInput = w.findAll('.app-card')[0].find('input[type="file"]')
    const file = new File([new Uint8Array([1, 2, 3])], 'ad.mp4', { type: 'video/mp4' })
    Object.defineProperty(fileInput.element, 'files', { value: [file], writable: false })
    await fileInput.trigger('change')
    await flushPromises()

    expect(upSpy).toHaveBeenCalledTimes(1)
    expect(upSpy.mock.calls[0][0]).toBe('/tg/avatar')
    expect(w.findAll('.app-card')[0].find('.ad-video-preview').exists()).toBe(true)
  })

  it('二级页该平台无功能页时显示空态', async () => {
    vi.spyOn(api, 'getDeployedApps').mockResolvedValue({ items: [], total: 0 } as any)
    const w = mount(SubmitCenterPanel)
    await flushPromises()
    await w.findAll('.apps-entry')[1].trigger('click') // telegram
    await flushPromises()
    expect(w.find('.apps-empty').exists()).toBe(true)
    expect(w.findAll('.app-card').length).toBe(0)
  })
})
