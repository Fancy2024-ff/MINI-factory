import { createApp } from 'vue'
import App from './App.vue'
import TgApp from './tg/TgApp.vue'
import './styles/tokens.css'
import './styles/global.css'

// 轻量入口分流：/tg* 进 Telegram WebApp，其余进工厂控制台。无 vue-router。
const isTg = window.location.pathname.replace(/\/+$/, '').startsWith('/tg')

createApp(isTg ? TgApp : App).mount('#app')
