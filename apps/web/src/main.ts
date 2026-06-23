import { createApp } from 'vue'
import App from './App.vue'
import TgApp from './tg/TgApp.vue'
import './styles/tokens.css'
import './styles/global.css'

// 入口分流：
// - /tg*          → Telegram WebApp（面向用户）
// - VITE_TG_ONLY=1（公网/CF 部署构建）→ 非 /tg 一律跳到 /tg，dashboard 后台不暴露
// - 否则（本地开发）→ 其余路径进工厂控制台 dashboard
const path = window.location.pathname.replace(/\/+$/, '')
const isTg = path.startsWith('/tg')
const tgOnly = import.meta.env.VITE_TG_ONLY === '1'

if (!isTg && tgOnly) {
  // 公网部署不暴露 dashboard：根路径等重定向到用户首页 /tg
  window.location.replace('/tg')
} else {
  createApp(isTg ? TgApp : App).mount('#app')
}
