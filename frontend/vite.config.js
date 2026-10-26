import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { mobileDevReconnect } from './plugins/mobileDevReconnect.js'
import { buildInfo } from './plugins/buildInfo.js'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

const mobileShell = process.env.STIMMA_MOBILE_SHELL === '1'

const backendPort = process.env.STIMMA_BACKEND_PORT || '9191'
const frontendPort = parseInt(process.env.STIMMA_FRONTEND_PORT || '9192', 10)

// Build distribution: 'dev' (default) | 'official' (set ONLY by release CI).
// Compile-time constant — gates the consent UI in the frontend.
const distribution = process.env.STIMMA_DISTRIBUTION === 'official' ? 'official' : 'dev'
const feedbackVariant = (officialPath, sourcePath) =>
  resolve(__dirname, distribution === 'official' ? officialPath : sourcePath)

const distributionAliases = [
  {
    find: '@stimma/feedback-root',
    replacement: feedbackVariant(
      'src/components/feedback/OfficialFeedbackRoot.vue',
      'src/components/feedback/SourceFeedbackRoot.vue'
    )
  },
  {
    find: '@stimma/feedback-footer-button',
    replacement: feedbackVariant(
      'src/components/feedback/OfficialFeedbackFooterButton.vue',
      'src/components/feedback/SourceFeedbackFooterButton.vue'
    )
  },
  {
    find: '@stimma/chat-thumb-buttons',
    replacement: feedbackVariant(
      'src/components/feedback/OfficialChatThumbButtons.vue',
      'src/components/feedback/SourceChatThumbButtons.vue'
    )
  },
  {
    find: '@stimma/prompt-agent-thumb-buttons',
    replacement: feedbackVariant(
      'src/components/feedback/OfficialPromptAgentThumbButtons.vue',
      'src/components/feedback/SourcePromptAgentThumbButtons.vue'
    )
  },
  {
    find: '@stimma/privacy-feedback-controls',
    replacement: feedbackVariant(
      'src/components/feedback/OfficialPrivacyFeedbackControls.vue',
      'src/components/feedback/SourcePrivacyFeedbackControls.vue'
    )
  }
]

export default defineConfig(() => ({
  // Build metadata stays out of the bundle (see plugins/buildInfo.js).
  plugins: [vue(), mobileDevReconnect(), buildInfo(__dirname)],
  build: {
    outDir: mobileShell ? 'dist-mobile' : 'dist',
    rollupOptions: {
      input: mobileShell ? { mobile: resolve(__dirname, 'mobile.html') } : { app: resolve(__dirname, 'index.html') },
    },
  },
  define: {
    __STIMMA_DISTRIBUTION__: JSON.stringify(distribution),
  },
  resolve: {
    alias: distributionAliases
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
