import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 前端 5173，/admin /chat /health 代理到后端 8000
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/admin': 'http://127.0.0.1:8000',
      '/chat': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
