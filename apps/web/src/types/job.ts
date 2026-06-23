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
