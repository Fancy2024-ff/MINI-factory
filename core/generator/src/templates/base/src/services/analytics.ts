// 增长/商业闭环埋点（下载漏斗）。
//
// 设计：
// - 纯本地：事件写 console + 一个有界的本地队列（uni storage + 内存兜底），不依赖外部服务。
// - 预留：未来若配置 analytics endpoint 可在此扩展上报，但当前不引入任何网络依赖。
// - 单测可读：getGrowthEvents() / clearGrowthEvents() 让测试断言事件顺序与失败原因。
//
// 这条漏斗证明「生成 → 预览 → 下载 → 激励广告 → 完播 → 去水印 → 保存」每一步可观测，
// 失败原因（未配置广告 / 中途关闭 / 广告错误 / 保存权限）可区分。

export type GrowthEventName =
  | 'result_view'
  | 'download_click'
  | 'rewarded_ad_request'
  | 'rewarded_ad_not_configured'
  | 'rewarded_ad_load_error'
  | 'rewarded_ad_show_error'
  | 'rewarded_ad_error'
  | 'rewarded_ad_closed_early'
  | 'rewarded_ad_completed'
  | 'download_unlocked'
  | 'watermark_removed'
  | 'export_start'
  | 'export_success'
  | 'export_failed'
  | 'save_permission_failed'

export interface GrowthEvent {
  name: GrowthEventName
  timestamp: number
  result_id?: string
  template?: string
  capability_mode?: string
  real_generation?: boolean
  export_kind?: string
  gate_type?: string
  ad_unit_configured?: boolean
  reason?: string
  [k: string]: any
}

const EVENTS_KEY = 'growth-events'
const MAX_EVENTS = 200

// 内存兜底队列：storage 不可用时（部分环境/单测）仍能读取断言。
let _memEvents: GrowthEvent[] = []

function readEvents(): GrowthEvent[] {
  try {
    const raw = uni.getStorageSync(EVENTS_KEY)
    if (Array.isArray(raw)) return raw as GrowthEvent[]
  } catch (e) {
    // ignore
  }
  return _memEvents
}

function writeEvents(events: GrowthEvent[]): void {
  _memEvents = events
  try {
    uni.setStorageSync(EVENTS_KEY, events)
  } catch (e) {
    // ignore storage errors（内存队列已保留）
  }
}

// 记录一条增长事件。payload 至少应带 result_id/template/capability_mode 等上下文（调用方提供）。
export function trackGrowthEvent(name: GrowthEventName, payload: Partial<GrowthEvent> = {}): GrowthEvent {
  const event: GrowthEvent = {
    name,
    timestamp: Date.now(),
    ...payload,
  }
  try {
    // 本地可见：console 便于真机 vConsole 观察漏斗。
    console.log('[growth-event]', name, JSON.stringify(payload))
  } catch (e) {
    // ignore
  }
  const events = readEvents()
  events.push(event)
  // 有界队列：超出上限丢弃最旧事件，避免 storage 膨胀。
  while (events.length > MAX_EVENTS) events.shift()
  writeEvents(events)
  return event
}

// 从结果对象提取通用埋点上下文（result_id/template/capability/gate 等）。
export function growthContextFromResult(result: any): Partial<GrowthEvent> {
  if (!result) return {}
  const gate = result.downloadGate
  return {
    result_id: result.id,
    template: result.template,
    capability_mode: result.capabilityMode,
    real_generation: result.realGeneration,
    gate_type: gate ? gate.gate_type : 'none',
    ad_unit_configured: !!(gate && gate.ad_unit_id),
  }
}

// 读取本地事件队列（单测/调试用）。
export function getGrowthEvents(): GrowthEvent[] {
  return readEvents().slice()
}

// 清空本地事件队列（单测用）。
export function clearGrowthEvents(): void {
  _memEvents = []
  try {
    uni.removeStorageSync(EVENTS_KEY)
  } catch (e) {
    // ignore
  }
}
