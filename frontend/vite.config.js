import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const backendPort = process.env.STIMMA_BACKEND_PORT || '9191'
const frontendPort = parseInt(process.env.STIMMA_FRONTEND_PORT || '9192', 10)

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  resolve: {
    alias: command === 'serve'
      ? [
          {
            find: '@',
            replacement: resolve(__dirname, '../packages/image-editor/src')
          },
          {
            find: '@stimma/image-editor/style.css',
            replacement: resolve(__dirname, '../packages/image-editor/src/styles/index.css')
          },
          {
            find: '@stimma/image-editor',
            replacement: resolve(__dirname, '../packages/image-editor/src/index.ts')
          }
        ]
      : []
  },
  server: {
    port: frontendPort,
    watch: {
      usePolling: true,
      interval: 300
    },
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true
      },
      '/ws': {
        target: `ws://127.0.0.1:${backendPort}`,
        ws: true,
        changeOrigin: true
      }
    }
  }
}))
