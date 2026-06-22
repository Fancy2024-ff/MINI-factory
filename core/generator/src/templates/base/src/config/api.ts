// Public API config for the generated mini-app.
// Provider credentials stay on apps/api; this file is safe to ship.
//
// 注意：本文件的 API_BASE / GENERATION_MODE 值由 codegen 在生成时按环境变量注入。
// 默认值保持 mock + 空 base，保证离线 / 未配置时闭环不依赖外部服务。
//
// 真机要点（微信小程序）：开启 api 模式时 API_BASE 必须是 https 绝对域名
// （如 https://api.example.com），且该域名要加入小程序后台「request 合法域名」，
// 否则 uni.request 会以 "url not in domain list" 失败。相对路径在真机无效。

export const API_BASE = '__API_BASE__'
export const GENERATION_MODE: 'mock' | 'api' = '__GENERATION_MODE__'
export const IMAGE_GENERATION_PATH = '/api/generation/image'
