import type { JobSummary, JobDetail, OpportunitySummary, PipelineMode } from '../types/job'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const WS_BASE = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000'
const API_KEY = import.meta.env.VITE_API_TOKEN || ''

class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, statusText: string, detail: any) {
    super(`${status} ${statusText}`)
    this.status = status
    this.detail = detail
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let detail: any = null
  try {
    const body = await res.json()
    detail = body?.detail ?? body
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, res.statusText, detail)
}

async function get<T = any>(path: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const res = await fetch(`${BASE}${path}`, { headers })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

async function post<T = any>(path: string, body?: any): Promise<T> {
  const headers: Record<string, string> = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export interface PipelineStartResult {
  accepted: boolean
  job_id: string
  mode: string
}

export interface PipelineStartOptions {
  regions?: string
  platforms?: string
  limit?: number
  max_generate?: number
}

export const api = {
  getJobs: () => get<{ jobs: JobSummary[] }>('/api/jobs'),
  getLatestJob: () => get<JobDetail>('/api/jobs/latest'),
  getJob: (id: string) => get<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`),
  startPipeline: (mode: PipelineMode = 'auto', options: PipelineStartOptions = {}) =>
    post<PipelineStartResult>('/api/pipeline/start', { mode, ...options }),
  stopPipeline: () => post('/api/pipeline/stop'),
  getPipelineStatus: () => get<{ running: boolean; job_id: string | null; log_lines: number }>('/api/pipeline/status'),
  getOpportunitySummary: () => get<OpportunitySummary>('/api/opportunities/summary'),
  getOpportunityQueue: () => get<{ items: any[]; total: number }>('/api/opportunities/queue'),
  getOpportunityCandidates: () => get<{ items: any[]; total: number }>('/api/opportunities/candidates'),
  getOpportunityFeatures: () => get<{ items: any[]; total: number }>('/api/opportunities/features'),
  getRealInputs: () => get<{ apps: any[]; exists: boolean }>('/api/real-inputs/apps'),
  saveRealInputs: (apps: any[]) => post('/api/real-inputs/apps', apps),
  getPlatforms: () => get<{ platforms: any[]; total: number }>('/api/platforms'),
  getPlatformAuth: () => get<{ platforms: any[] }>('/api/platform-auth/status'),
  uploadWechat: () => post<{ upload_passed: boolean; reason: string }>('/api/platforms/wechat/upload'),
}

export interface WSCallbacks {
  onMessage: (data: any) => void
  onError?: (info: { code?: number; reason?: string }) => void
  onClose?: () => void
  onReconnect?: (attempt: number) => void
}

export interface WSHandle {
  disconnect: () => void
}

/**
 * Connect to the per-job pipeline WebSocket with bounded exponential-backoff
 * reconnection. Stops after `maxRetries` attempts and reports via onClose.
 * Code 4001 = unauthorized token → reported via onError and not retried.
 */
export function connectPipelineWS(
  jobId: string,
  arg: ((data: any) => void) | WSCallbacks,
  maxRetries = 8,
): WSHandle {
  const cbs: WSCallbacks = typeof arg === 'function' ? { onMessage: arg } : arg
  let ws: WebSocket | null = null
  let retryCount = 0
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | null = null

  function connect() {
    if (stopped) return
    const tokenParam = API_KEY ? `?token=${encodeURIComponent(API_KEY)}` : ''
    ws = new WebSocket(`${WS_BASE}/ws/pipeline/${encodeURIComponent(jobId)}${tokenParam}`)
    ws.onopen = () => { retryCount = 0 }
    ws.onmessage = (e) => {
      try { cbs.onMessage(JSON.parse(e.data)) } catch { /* ignore */ }
    }
    ws.onerror = () => { /* close handler drives retry */ }
    ws.onclose = (ev) => {
      if (stopped) return
      // 4001 = unauthorized: do not retry, surface auth failure.
      if (ev.code === 4001) {
        cbs.onError?.({ code: ev.code, reason: ev.reason || 'unauthorized' })
        cbs.onClose?.()
        return
      }
      if (retryCount >= maxRetries) {
        cbs.onClose?.()
        return
      }
      const delay = Math.min(1000 * Math.pow(2, retryCount), 30000)
      retryCount++
      cbs.onReconnect?.(retryCount)
      timer = setTimeout(connect, delay)
    }
  }

  connect()

  return {
    disconnect() {
      stopped = true
      if (timer) { clearTimeout(timer); timer = null }
      if (ws) { ws.close(); ws = null }
    },
  }
}
