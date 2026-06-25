import generated from './features.generated.json'

export type Ability = 'text2img' | 'img2img'
export type Task = 'generate_image' | 'background_remove' | 'watermark_remove'

export interface FeatureConfig {
  id: string
  title: string
  icon: string
  ability: Ability
  task: Task
  subtitle: string
  input: { imageRequired?: boolean; textRequired?: boolean; acceptedTypes?: string[] }
  params: { promptTemplate?: string; task?: string; outputMode?: string }
  ui: { textPlaceholder?: string; uploadLabel?: string; submitLabel: string; resultTitle?: string }
  source?: { type?: string; confidence?: number }
}

const ABILITY_WHITELIST = new Set<string>(['text2img', 'img2img'])
const TASK_WHITELIST = new Set<string>(['generate_image', 'background_remove', 'watermark_remove'])

export function validateFeature(f: FeatureConfig): { ok: boolean; reason: string } {
  if (!f || !/^[a-z0-9-]+$/.test(f.id || '')) return { ok: false, reason: 'id not url-safe' }
  for (const k of ['title', 'icon', 'ability', 'task', 'subtitle'] as const) {
    if (!f[k]) return { ok: false, reason: `missing ${k}` }
  }
  if (!ABILITY_WHITELIST.has(f.ability)) return { ok: false, reason: 'ability' }
  if (!TASK_WHITELIST.has(f.task)) return { ok: false, reason: 'task' }
  if (!f.ui?.submitLabel) return { ok: false, reason: 'ui.submitLabel' }
  if (f.ability === 'img2img' && !f.input?.imageRequired) return { ok: false, reason: 'imageRequired' }
  if (f.ability === 'text2img' && !f.input?.textRequired) return { ok: false, reason: 'textRequired' }
  return { ok: true, reason: '' }
}

// 加载时过滤掉非法项，保证 UI 只见合法 feature（坏项不致整页崩）。
const _valid: FeatureConfig[] = (generated as FeatureConfig[]).filter(
  (f) => validateFeature(f).ok,
)

export function getGeneratedFeatures(): FeatureConfig[] {
  return _valid
}

export function getFeatureById(id: string): FeatureConfig | undefined {
  return _valid.find((f) => f.id === id)
}
