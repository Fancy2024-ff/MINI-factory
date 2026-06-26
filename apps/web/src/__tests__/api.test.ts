import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, connectPipelineWS } from '../services/api'

// --- Minimal WebSocket mock ------------------------------------------------
class MockWS {
  static instances: MockWS[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((e: any) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((e: any) => void) | null = null
  closed = false
  constructor(url: string) {
    this.url = url
    MockWS.instances.push(this)
  }
  close() { this.closed = true }
  // helpers
  fireClose(code = 1006, reason = '') { this.onclose?.({ code, reason }) }
}

beforeEach(() => {
  MockWS.instances = []
  vi.stubGlobal('WebSocket', MockWS as any)
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('api.startPipeline', () => {
  it('posts auto mode with explicit safe launch options', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ accepted: true, job_id: 'job-1', mode: 'auto' }),
    } as any)
    vi.stubGlobal('fetch', fetchMock)

    await api.startPipeline('auto', {
      regions: 'CN,US',
      platforms: 'app_store',
      limit: 10,
      max_generate: 1,
    })

    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({
      mode: 'auto',
      regions: 'CN,US',
      platforms: 'app_store',
      limit: 10,
      max_generate: 1,
    })
  })

  it('passes force_refresh through to the start payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ accepted: true, job_id: 'job-2', mode: 'auto' }),
    } as any)
    vi.stubGlobal('fetch', fetchMock)

    await api.startPipeline('auto', {
      regions: 'CN', platforms: 'app_store', limit: 5, max_generate: 1, force_refresh: true,
    })

    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body).force_refresh).toBe(true)
  })
})

describe('api.processedApps', () => {
  it('GET hits the processed endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ count: 0, features: [] }),
    } as any)
    vi.stubGlobal('fetch', fetchMock)
    await api.getProcessedApps()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/opportunities/processed')
    expect(init?.method ?? 'GET').toBe('GET')
  })

  it('reset POSTs the body to the reset endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, removed: 2, remaining: 0, backup: 'b.json' }),
    } as any)
    vi.stubGlobal('fetch', fetchMock)
    await api.resetProcessedApps({ feature_key: 'k1' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/opportunities/processed/reset')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ feature_key: 'k1' })
  })
})

describe('connectPipelineWS', () => {
  it('encodes the jobId with encodeURIComponent in the WS url', () => {
    // jobId with spaces should be percent-encoded in the URL path
    connectPipelineWS('job 1', () => {})
    const url = MockWS.instances[0].url
    expect(url).toContain('/ws/pipeline/job%201')
    expect(url).not.toContain('/ws/pipeline/job 1')
  })

  it('does NOT reconnect on 4001 unauthorized and reports onError', () => {
    const onError = vi.fn()
    const onClose = vi.fn()
    connectPipelineWS('j', { onMessage: () => {}, onError, onClose })
    expect(MockWS.instances.length).toBe(1)
    MockWS.instances[0].fireClose(4001, 'unauthorized')
    vi.advanceTimersByTime(60000)
    // no second socket created
    expect(MockWS.instances.length).toBe(1)
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 4001 }))
    expect(onClose).toHaveBeenCalled()
  })

  it('reconnects with backoff then calls onClose after maxRetries', () => {
    const onClose = vi.fn()
    const onReconnect = vi.fn()
    connectPipelineWS('j', { onMessage: () => {}, onClose, onReconnect }, 2)
    // attempt 1 -> close, schedules retry
    MockWS.instances[0].fireClose(1006)
    vi.advanceTimersByTime(2000)
    expect(MockWS.instances.length).toBe(2)
    // attempt 2 -> close, schedules retry
    MockWS.instances[1].fireClose(1006)
    vi.advanceTimersByTime(4000)
    expect(MockWS.instances.length).toBe(3)
    // attempt 3 -> close, retryCount(2) >= maxRetries(2) -> onClose, no new socket
    MockWS.instances[2].fireClose(1006)
    vi.advanceTimersByTime(60000)
    expect(MockWS.instances.length).toBe(3)
    expect(onClose).toHaveBeenCalled()
    expect(onReconnect).toHaveBeenCalled()
  })

  it('disconnect stops further reconnection', () => {
    const handle = connectPipelineWS('j', () => {})
    handle.disconnect()
    MockWS.instances[0].fireClose(1006)
    vi.advanceTimersByTime(60000)
    expect(MockWS.instances.length).toBe(1)
  })
})
