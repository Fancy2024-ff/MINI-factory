// TG WebApp 轻量路由：路径归一化。无 vue-router，供 TgApp 与测试共用。

export type TgRoute =
  | '/tg'
  | '/tg/ai-image'
  | '/tg/avatar'
  | '/tg/sticker'
  | '/tg/pet-talk'

export function normalizeRoute(path: string): TgRoute {
  const p = (path || '/tg').replace(/\/+$/, '') || '/tg'
  if (p === '/tg/ai-image') return '/tg/ai-image'
  if (p === '/tg/avatar') return '/tg/avatar'
  if (p === '/tg/sticker') return '/tg/sticker'
  if (p === '/tg/pet-talk') return '/tg/pet-talk'
  return '/tg'
}
