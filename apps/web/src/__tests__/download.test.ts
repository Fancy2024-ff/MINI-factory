// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { sliceGrid, downloadImage } from '../tg/download'

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
