import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 前端 5173，/admin /chat /health 代理到后端 8000
// base 为 /console/：生产环境由 OpenResty 托管在 ffp.hikoutei.cn/console/，
// 与 API 同源，因此后端不需要放行任何 CORS 来源。
export default defineConfig({
  plugins: [react()],
  base: '/console/',
  server: {
    port: 5173,
    proxy: {
      '/admin': 'http://127.0.0.1:8000',
      '/chat': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
