import { describe, it, expect, vi, afterEach } from 'vitest'
import { toDisplayImage, templateResultToDisplay, MAX_PROMPT_LEN } from '../tg/tgApi'
import { normalizeRoute } from '../tg/route'
import type { ImageResult } from '../tg/types'

describe('tg route normalize', () => {
  it('maps /tg and trailing slash to /tg', () => {
    expect(normalizeRoute('/tg')).toBe('/tg')
    expect(normalizeRoute('/tg/')).toBe('/tg')
    expect(normalizeRoute('')).toBe('/tg')
  })
  it('maps ai-image route', () => {
    expect(normalizeRoute('/tg/ai-image')).toBe('/tg/ai-image')
    expect(normalizeRoute('/tg/ai-image/')).toBe('/tg/ai-image')
  })
  it('maps avatar route', () => {
    expect(normalizeRoute('/tg/avatar')).toBe('/tg/avatar')
    expect(normalizeRoute('/tg/avatar/')).toBe('/tg/avatar')
  })
  it('falls back unknown to /tg', () => {
    expect(normalizeRoute('/tg/unknown')).toBe('/tg')
    expect(normalizeRoute('/other')).toBe('/tg')
  })
})

describe('toDisplayImage', () => {
  it('prefers image_url', () => {
    const r: ImageResult = { preview_type: 'image', image_url: 'https://x/y.png', image_base64: 'QUJD' }
    const d = toDisplayImage(r)
    expect(d?.src).toBe('https://x/y.png')
  })
  it('builds data URI from base64 when no url', () => {
    const r: ImageResult = { preview_type: 'image', image_url: null, image_base64: 'QUJD' }
    const d = toDisplayImage(r)
    expect(d?.src).toBe('data:image/jpeg;base64,QUJD')
  })
  it('returns null when neither present', () => {
    const r: ImageResult = { preview_type: 'image', image_url: null, image_base64: null }
    expect(toDisplayImage(r)).toBeNull()
    expect(toDisplayImage(undefined)).toBeNull()
  })
  it('exposes a prompt length cap', () => {
    expect(MAX_PROMPT_LEN).toBeGreaterThan(0)
    expect(MAX_PROMPT_LEN).toBeLessThanOrEqual(1000)
  })
})

describe('templateResultToDisplay', () => {
  it('builds data URI from base64 with avatar fallback title', () => {
    const d = templateResultToDisplay({ image_base64: 'QUJD', prompt: 'p' })
    expect(d?.src).toBe('data:image/jpeg;base64,QUJD')
    expect(d?.title).toBe('AI 头像已生成')
  })
  it('prefers image_url and given title', () => {
    const d = templateResultToDisplay({ image_url: 'https://x/y.png', title: 'T' })
    expect(d?.src).toBe('https://x/y.png')
    expect(d?.title).toBe('T')
  })
  it('returns null when no image', () => {
    expect(templateResultToDisplay({ image_url: null, image_base64: null })).toBeNull()
    expect(templateResultToDisplay(undefined)).toBeNull()
  })
})

describe('generateImage error mapping', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('returns structured network error without leaking internals', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED deep detail')))
    const { generateImage } = await import('../tg/tgApi')
    const resp = await generateImage({ template_id: 'ai-image', prompt: 'x', style: 'realistic', aspect_ratio: '1:1' })
    expect(resp.ok).toBe(false)
    expect(resp.error?.code).toBe('NETWORK_ERROR')
    expect(JSON.stringify(resp)).not.toContain('ECONNREFUSED')
  })

  it('maps non-ok http to structured error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 } as any))
    const { generateImage } = await import('../tg/tgApi')
    const resp = await generateImage({ template_id: 'ai-image', prompt: 'x', style: 'realistic', aspect_ratio: '1:1' })
    expect(resp.ok).toBe(false)
    expect(resp.error?.code).toBe('HTTP_ERROR')
  })
})

describe('generateTemplate error mapping', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('returns structured network error without leaking internals', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED deep detail')))
    const { generateTemplate } = await import('../tg/tgApi')
    const resp = await generateTemplate({ template_id: 'avatar-viral', input: { prompt: 'x' } })
    expect(resp.ok).toBe(false)
    expect(resp.error?.code).toBe('NETWORK_ERROR')
    expect(JSON.stringify(resp)).not.toContain('ECONNREFUSED')
  })
})
