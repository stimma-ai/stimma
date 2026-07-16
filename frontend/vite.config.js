import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { fileURLToPath } from 'url'
import { execSync } from 'child_process'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

let commitHash = ''
try {
  commitHash = execSync('git rev-parse --short HEAD', { cwd: __dirname }).toString().trim()
} catch {
  // not a git checkout (e.g. source tarball) — omit the hash
}

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
    find: '@stimma/logo-feedback-menu',
    replacement: feedbackVariant(
      'src/components/feedback/OfficialLogoFeedbackMenu.vue',
      'src/components/feedback/SourceLogoFeedbackMenu.vue'
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

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  define: {
    __STIMMA_DISTRIBUTION__: JSON.stringify(distribution),
    __STIMMA_COMMIT__: JSON.stringify(commitHash),
  },
  resolve: {
    alias: command === 'serve'
      ? [
          ...distributionAliases,
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
      : distributionAliases
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
