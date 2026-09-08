import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api to the local FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // watch 增量构建时不清空 dist：服务器正在伺服该目录，清空会让页面瞬间 404。
    emptyOutDir: false,
    chunkSizeWarningLimit: 1500,
  },
})
