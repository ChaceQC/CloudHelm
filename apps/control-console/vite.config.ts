import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * 控制台 Vite 配置。
 *
 * M1 只启用 React 插件和本地开发服务器，桌面端 Tauri 构建目标
 * 会在控制台主流程落地后再补充，避免当前阶段引入未验证能力。
 */
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
})
