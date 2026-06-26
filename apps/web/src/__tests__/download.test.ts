// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { sliceGrid, downloadImage, useDownloadGate } from '../tg/download'

vi.mock('../tg/tgApi', () => ({
  sendToChat: vi.fn(),
}))
import { sendToChat } from '../tg/tgApi'

// jsdom 不实现 canvas 绘制；这里桩掉 Image 的 onload 与 canvas.getContext/toDataURL，
// 只验证 sliceGrid 的切分逻辑（格数、尺寸、产出数量、异常兜底），不验证真实像素。
function stubImage(naturalWidth: number, naturalHeight: number, fail = false) {
  class FakeImage {
    crossOrigin = ''
    naturalWidth = naturalWidth
    naturalHeight = naturalHeight
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    set src(_v: string) {
      // 异步触发，贴近真实 Image 行为
      setTimeout(() => (fail ? this.onerror?.() : this.onload?.()), 0)
    }
  }
  vi.stubGlobal('Image', FakeImage as any)
}

function stubCanvas(opts: { ctx?: boolean; throwOnDataUrl?: boolean } = {}) {
  const drawCalls: any[] = []
  const origCreate = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    if (tag !== 'canvas') return origCreate(tag)
    return {
      width: 0,
      height: 0,
      getContext: () =>
        opts.ctx === false
          ? null
          : { drawImage: (...a: any[]) => drawCalls.push(a) },
      toDataURL: () => {
        if (opts.throwOnDataUrl) throw new Error('SecurityError')
        return 'data:image/png;base64,FAKE'
      },
    } as any
  })
  return drawCalls
}

afterEach(() => vi.unstubAllGlobals())

describe('sliceGrid', () => {
  it('slices a grid into rows*cols cells', async () => {
    stubImage(300, 300)
    stubCanvas()
    const out = await sliceGrid('http://x/sheet.png', 3, 3)
    expect(out.length).toBe(9)
    expect(out.every((s) => s.startsWith('data:image/png'))).toBe(true)
  })

  it('respects custom rows/cols', async () => {
    stubImage(200, 100)
    stubCanvas()
    const out = await sliceGrid('http://x/sheet.png', 1, 2)
    expect(out.length).toBe(2)
  })

  it('returns [] when the image fails to load', async () => {
    stubImage(0, 0, true)
    stubCanvas()
    const out = await sliceGrid('http://x/broken.png')
    expect(out).toEqual([])
  })

  it('returns [] when image has zero dimensions', async () => {
    stubImage(0, 0)
    stubCanvas()
    const out = await sliceGrid('http://x/empty.png')
    expect(out).toEqual([])
  })

  it('skips cells that throw on toDataURL (tainted canvas) without crashing', async () => {
    stubImage(300, 300)
    stubCanvas({ throwOnDataUrl: true })
    const out = await sliceGrid('http://x/sheet.png')
    expect(out).toEqual([]) // 全部格 toDataURL 抛错 → 安全产出空，不崩
  })
})

describe('downloadImage 在 Telegram 内对 base64 走「发送到聊天」', () => {
  afterEach(() => {
    delete (window as any).Telegram
    vi.mocked(sendToChat).mockReset()
  })

  it('TG 内 + base64：调用 sendToChat，成功返回 sent，不走 <a download>', async () => {
    ;(window as any).Telegram = { WebApp: { initData: 'x' } }
    vi.mocked(sendToChat).mockResolvedValue({ ok: true })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const r = await downloadImage('data:image/png;base64,QUJD', 'a.png')

    expect(r).toBe('sent')
    expect(sendToChat).toHaveBeenCalledWith('data:image/png;base64,QUJD', '')
    expect(clickSpy).not.toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('TG 内 + base64：sendToChat 失败时兜底尝试 <a download>', async () => {
    ;(window as any).Telegram = { WebApp: { initData: 'x' } }
    vi.mocked(sendToChat).mockResolvedValue({ ok: false, error: { code: 'BOT_BLOCKED', message: '' } })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const r = await downloadImage('data:image/png;base64,QUJD', 'a.png')

    expect(sendToChat).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()  // 兜底走了 anchor
    expect(r).toBe('downloaded')
    clickSpy.mockRestore()
  })
})

describe('downloadImage 普通浏览器（非 Telegram）', () => {
  const origUA = navigator.userAgent

  afterEach(() => {
    delete (window as any).Telegram
    Object.defineProperty(navigator, 'userAgent', { value: origUA, configurable: true })
    Object.defineProperty(navigator, 'maxTouchPoints', { value: 0, configurable: true })
    vi.restoreAllMocks()
  })

  it('iOS Safari + base64：新标签打开（让用户长按存相册），不假装已下载', async () => {
    delete (window as any).Telegram
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
      configurable: true,
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, blob: async () => new Blob(['x'], { type: 'image/png' }),
    } as any))
    ;(URL as any).createObjectURL = vi.fn(() => 'blob:fake')
    const openSpy = vi.spyOn(window, 'open').mockReturnValue({} as any)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const r = await downloadImage('data:image/png;base64,QUJD', 'a.png')

    expect(r).toBe('opened')
    expect(openSpy).toHaveBeenCalledWith('blob:fake', '_blank')
    expect(clickSpy).not.toHaveBeenCalled()  // iOS 不走注定失败的 <a download>
  })

  it('桌面浏览器 + base64：先转 blob URL 再 <a download>', async () => {
    delete (window as any).Telegram
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Chrome/120',
      configurable: true,
    })
    Object.defineProperty(navigator, 'maxTouchPoints', { value: 0, configurable: true })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, blob: async () => new Blob(['x'], { type: 'image/png' }),
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

    const r = await downloadImage('data:image/png;base64,QUJD', 'a.png')

    expect(r).toBe('downloaded')
    expect(anchors[0].href).toContain('blob:')   // 用的是 blob URL 不是 data URI
    expect(anchors[0].download).toBe('a.png')
  })
})

describe('useDownloadGate 广告开关/时长（运行时配置）', () => {
  it('默认启用：requestDownload 弹广告闸门，不立即下载', () => {
    const gate = useDownloadGate()
    let downloaded = false
    gate.requestDownload(() => { downloaded = true })
    expect(gate.adVisible.value).toBe(true)
    expect(downloaded).toBe(false)
  })

  it('configure({enabled:false})：下架广告，下载直接执行不弹闸门', () => {
    const gate = useDownloadGate()
    gate.configure({ enabled: false })
    let downloaded = false
    gate.requestDownload(() => { downloaded = true })
    expect(gate.adVisible.value).toBe(false)
    expect(downloaded).toBe(true)
  })

  it('configure({seconds:0})：时长 0 等同直接放行', () => {
    const gate = useDownloadGate()
    gate.configure({ seconds: 0 })
    let downloaded = false
    gate.requestDownload(() => { downloaded = true })
    expect(gate.adVisible.value).toBe(false)
    expect(downloaded).toBe(true)
  })

  it('configure 自定义时长：闸门倒计时用新秒数', () => {
    const gate = useDownloadGate()
    gate.configure({ seconds: 15 })
    gate.requestDownload(() => {})
    expect(gate.adRemain.value).toBe(15)
  })

  it('configure({videoUrl}) 暴露视频地址供遮罩播放', () => {
    const gate = useDownloadGate()
    gate.configure({ videoUrl: 'https://api/x/ad.mp4' })
    expect(gate.videoUrl.value).toBe('https://api/x/ad.mp4')
  })
})
