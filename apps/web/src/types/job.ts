export interface JobSummary {
  id: string
  path: string
  app_name?: string
  app_name_en?: string
  qa_passed?: boolean
  build_verified?: boolean
  artifacts?: string[]
  has_miniapp?: boolean
}

export interface JobDetail {
  id: string
  path: string
  artifacts: Record<string, any>
  miniapp_files?: string[]
  miniapp_path?: string
}

// 传播闭环摘要（来自 generator-source.json / codegen_report，P0-2）。
// 前端 dashboard 据此显示「生成的小程序带不带传播机制」，无需解析整段 blueprint。
export interface GrowthLoopSummary {
  growth_loop_present?: boolean
  has_share_cta?: boolean
  share_cta_label?: string
  has_unlock?: boolean
  unlock_type?: string
  has_watermark?: boolean
  remove_watermark_supported?: boolean
  brand_exposure?: boolean
  download_supported?: boolean
  export_supported?: boolean
  capability_mode?: 'real' | 'fallback_preview' | ''
}

export interface PipelineStep {
  step?: string
  name: string
  capability?: string
  status: string
  artifact?: string
  duration_ms?: number
  started_at?: string
  finished_at?: string
  error?: string
  user_message?: string
}

export type PipelineMode = 'auto' | 'crawl' | 'queue' | 'demo' | 'real'
export type OpportunityView = 'queue' | 'candidates' | 'features'

export interface PipelineLaunchOptions {
  regions: string
  platforms: string
  limit: number
  max_generate: number
}

export interface OpportunitySummary {
  exists: boolean
  updated_at?: string
  crawl_stats?: Record<string, any>
  dedup_stats?: Record<string, any>
  feature_stats?: Record<string, any>
  queue_stats?: Record<string, any>
  top_templates?: Record<string, number>
  top_queue?: any[]
  top_candidates?: any[]
  top_features?: any[]
}

export interface DemoResult {
  success: boolean
  job_id: string | null
  exit_code: number
  log_lines: number
  logs: string[]
}

// 生产任务系统（task_store/task_worker）。前端只读 + 触发 cancel/retry，不碰底层逻辑。
export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type TaskKind = 'pipeline.run' | 'pipeline.auto' | 'opportunity.crawl'

export interface TaskItem {
  id: string
  kind: TaskKind | string
  status: TaskStatus | string
  priority: number
  attempts: number
  max_attempts: number
  queue_id?: string | null
  job_id?: string | null
  error_code?: string | null
  error_message?: string | null
  created_at?: string
  updated_at?: string
  started_at?: string | null
  finished_at?: string | null
  payload?: Record<string, any>
  result?: Record<string, any> | null
}

export interface TaskSummary {
  total: number
  by_status: Record<string, number>
  by_kind: Record<string, number>
}

// generate_now 现在走 task queue：返回任务句柄（含去重复用标记）。
export interface QueueActionResult {
  ok: boolean
  action: string
  queue_id: string
  accepted?: boolean
  reused?: boolean
  task_id?: string
  kind?: string
  status?: string
  job_id?: string | null
  mode?: string
}
