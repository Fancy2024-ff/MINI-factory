import type { JobSummary, JobDetail, OpportunitySummary, PipelineMode, TaskItem, TaskSummary, TaskHealth, QueueActionResult } from '../types/job'

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

// multipart 上传（不设 Content-Type，交给浏览器带 boundary）。
async function postForm<T = any>(path: string, form: FormData): Promise<T> {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: form })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

async function del<T = any>(path: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

// 下载 zip 产物（小程序源码 / 构建产物 / 整包）。用带认证头的 fetch 取 blob 再触发
// 浏览器保存——直接用 <a href> 无法携带 X-API-Key，开了鉴权就会 401。
async function downloadZip(path: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const res = await fetch(`${BASE}${path}`, { headers })
  if (!res.ok) throw await parseError(res)
  // 优先用后端 Content-Disposition 的文件名。
  const disp = res.headers.get('Content-Disposition') || ''
  const m = disp.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)
  const filename = m ? decodeURIComponent(m[1]) : fallbackName
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export interface PipelineStartResult {
  accepted: boolean
  job_id: string
  mode: string
  task_id?: string
  execution_mode?: string
}

export interface PipelineStartOptions {
  regions?: string
  platforms?: string
  limit?: number
  max_generate?: number
  force_refresh?: boolean
}

export const api = {
  getJobs: () => get<{ jobs: JobSummary[] }>('/api/jobs'),
  getLatestJob: () => get<JobDetail>('/api/jobs/latest'),
  getJob: (id: string) => get<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`),
  // 下载 job 产物 zip。target: all（整包）/ miniapp（小程序源码）/ dist（构建产物）。
  downloadJobZip: (id: string, target: 'all' | 'miniapp' | 'dist' = 'all') =>
    downloadZip(
      `/api/jobs/${encodeURIComponent(id)}/download?target=${target}`,
      `miniapp-factory-${id}-${target}.zip`,
    ),
  startPipeline: (mode: PipelineMode = 'auto', options: PipelineStartOptions = {}) =>
    post<PipelineStartResult>('/api/pipeline/start', { mode, ...options }),
  stopPipeline: () => post('/api/pipeline/stop'),
  getPipelineStatus: () => get<{ running: boolean; job_id: string | null; log_lines: number }>('/api/pipeline/status'),
  getOpportunitySummary: () => get<OpportunitySummary>('/api/opportunities/summary'),
  getOpportunityQueue: () => get<{ items: any[]; total: number }>('/api/opportunities/queue'),
  getOpportunityCandidates: () => get<{ items: any[]; total: number }>('/api/opportunities/candidates'),
  getOpportunityFeatures: () => get<{ items: any[]; total: number }>('/api/opportunities/features'),
  // processed-apps 记录：查看哪些 feature 被永久从候选隐藏 + 重置（破坏性，后端自动备份）。
  getProcessedApps: () => get<{ count: number; features: any[] }>('/api/opportunities/processed'),
  resetProcessedApps: (body: { all?: boolean; feature_key?: string } = {}) =>
    post<{ ok: boolean; removed: number; remaining: number; backup: string | null }>(
      '/api/opportunities/processed/reset',
      body,
    ),
  queueAction: (action: 'prioritize' | 'skip' | 'retry' | 'generate_now', queueId: string, payload: any = {}) =>
    post<QueueActionResult>(
      '/api/opportunities/queue/action',
      { action, queue_id: queueId, payload },
    ),
  // 生产任务系统（只读 + cancel/retry）。底层逻辑在 core.runtime/task_worker，前端不碰。
  getTasks: (params: { status?: string; kind?: string; queue_id?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams()
    if (params.status) qs.set('status', params.status)
    if (params.kind) qs.set('kind', params.kind)
    if (params.queue_id) qs.set('queue_id', params.queue_id)
    if (params.limit) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return get<{ tasks: TaskItem[]; count: number }>(`/api/tasks${suffix}`)
  },
  getTaskSummary: () => get<TaskSummary>('/api/tasks/summary'),
  getTaskHealth: () => get<TaskHealth>('/api/tasks/health'),
  getTask: (id: string) => get<TaskItem>(`/api/tasks/${encodeURIComponent(id)}`),
  getTasksByQueue: (queueId: string) =>
    get<{ queue_id: string; tasks: TaskItem[]; count: number }>(
      `/api/tasks/by-queue/${encodeURIComponent(queueId)}`,
    ),
  cancelTask: (id: string) =>
    post<{ ok: boolean; task_id: string; status: string }>(`/api/tasks/${encodeURIComponent(id)}/cancel`),
  retryTask: (id: string) =>
    post<{ ok: boolean; task_id: string; status: string }>(`/api/tasks/${encodeURIComponent(id)}/retry`),
  getRealInputs: () => get<{ apps: any[]; exists: boolean }>('/api/real-inputs/apps'),
  saveRealInputs: (apps: any[]) => post('/api/real-inputs/apps', apps),
  getPlatforms: () => get<{ platforms: any[]; total: number }>('/api/platforms'),
  getPlatformAuth: () => get<{ platforms: any[] }>('/api/platform-auth/status'),
  uploadWechat: () => post<{ upload_passed: boolean; reason: string }>('/api/platforms/wechat/upload'),
  // 提交中心：已上架功能页（含预览 URL + 当前广告配置）。
  getDeployedApps: () => get<{ items: any[]; total: number }>('/api/submit/deployed-apps'),
  // 提交中心：更新某功能页广告闸门（上架/下架 + 时长）。
  saveAdConfig: (route: string, adEnabled?: boolean, adSeconds?: number) =>
    post<{ ok: boolean; route: string; ad: { ad_enabled: boolean; ad_seconds: number } }>(
      '/api/submit/ad-config',
      { route, ad_enabled: adEnabled, ad_seconds: adSeconds },
    ),
  // 提交中心：上传/删除某功能页的广告视频。
  uploadAdVideo: (route: string, file: File) => {
    const form = new FormData()
    form.append('route', route)
    form.append('video', file)
    return postForm<{ ok: boolean; route: string; video_url: string }>('/api/submit/ad-video', form)
  },
  deleteAdVideo: (route: string) =>
    del<{ ok: boolean; route: string; video_url: string }>(
      `/api/submit/ad-video?route=${encodeURIComponent(route)}`,
    ),
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
