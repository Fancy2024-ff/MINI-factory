import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

// 把所有路径锚定到本项目目录，避免 vite 在某些 Windows 权限环境下
// 向上递归探测配置/工作区（"../../../../.."）命中无权限目录而报 "Access is denied"。
// vitest 配置见同目录 vitest.config.ts（独立文件，避免 vitest 的 vite 类型与 vite 8 冲突）。
const projectRoot = dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  root: projectRoot,
  cacheDir: resolve(projectRoot, 'node_modules/.vite'),
  plugins: [vue()],
})
