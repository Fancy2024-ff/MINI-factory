import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'

// 独立的 vitest 配置：从 vitest/config 引入 defineConfig，test 字段类型安全。
// 该文件不在 tsconfig.node.json/app.json 的 include 中，因此不会被 vue-tsc -b
// 类型检查，规避 vitest 自带 vite 类型与本项目 vite 8 的类型冲突。
// root 锚定到本目录，避免向上递归探测命中无权限目录（Windows "Access is denied"）。
const projectRoot = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root: projectRoot,
  // 加载 vue 插件以支持 .vue 组件渲染测试（TG WebApp 页面）。
  plugins: [vue()],
  test: {
    root: projectRoot,
    // 默认 node（逻辑测试）；需要 DOM 的用例在文件首行用 // @vitest-environment jsdom。
    environment: 'node',
    include: ['src/**/*.{test,spec}.{ts,js}'],
    watch: false,
  },
})
