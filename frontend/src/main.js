import { createApp } from 'vue'
import { initApiConfig, isTauri, setStartupStatusCallback } from './apiConfig'
// Import useProfile early to set up the global fetch interceptor before any API calls
import './composables/useProfile'
import { initializeCurrentProfile } from './composables/useProfile'
import router from './router'
import App from './App.vue'
import './style.css'
import {
  isEditorDebugEnabled,
  logEditorDebug,
  getRecentEditorDebugEvents,
  summarizeEditorDebugError,
} from '../../packages/image-editor/src/utils/editorDebug'

// Show loading screen for Tauri mode
function showLoadingScreen() {
  const appDiv = document.getElementById('app')
  appDiv.innerHTML = `
    <div style="
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      background: var(--color-base, #0b0e14);
    ">
      <div data-tauri-drag-region style="
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 56px;
      "></div>
      <img
        src="/logo.png"
        alt="Stimma"
        style="
          width: 80px;
          height: 80px;
          animation: pendulum 2.4s ease-in-out infinite;
        "
      />
    </div>
    <style>
      @keyframes pendulum {
        0%, 100% { transform: rotate(-175deg); }
        50% { transform: rotate(175deg); }
      }
    </style>
  `
}

function updateStatus(status) {
  const el = document.getElementById('startup-status')
  if (el) el.textContent = status
}

function showError(message) {
  const appDiv = document.getElementById('app')
  appDiv.innerHTML = `
    <div style="
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      background: var(--color-base, #0b0e14);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    ">
      <div style="
        width: 320px;
        background: #27272a;
        border: 1px solid #3f3f46;
        border-radius: 8px;
        padding: 24px;
        text-align: center;
      ">
        <div style="
          width: 64px;
          height: 64px;
          margin: 0 auto 16px;
          border-radius: 50%;
          background: rgba(239, 68, 68, 0.2);
          display: flex;
          align-items: center;
          justify-content: center;
        ">
          <svg style="width: 32px; height: 32px; color: #f87171;" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
        </div>
        <h1 style="
          font-size: 20px;
          font-weight: 600;
          color: #f4f4f5;
          margin: 0 0 8px 0;
        ">Stimma failed to start</h1>
        <p style="
          font-size: 14px;
          color: #a1a1aa;
          margin: 0;
        ">${message}</p>
      </div>
    </div>
  `
}

// Show loading screen in Tauri mode
if (isTauri()) {
  showLoadingScreen()
  setStartupStatusCallback(updateStatus)
}

// Initialize API config (handles Tauri port detection) before mounting
initApiConfig().then(() => {
  return initializeCurrentProfile()
}).then(() => {
  const app = createApp(App)
  app.use(router)

  if (isEditorDebugEnabled()) {
    app.config.warnHandler = (msg, instance, trace) => {
      logEditorDebug('Vue', 'warn', {
        message: msg,
        component: instance?.type?.name ?? null,
        trace,
        route: router.currentRoute.value.fullPath,
      })
      console.warn('[EditorDebug] Vue warn', msg, trace)
    }

    app.config.errorHandler = (error, instance, info) => {
      const errorSummary = summarizeEditorDebugError(error)
      const recentEvents = getRecentEditorDebugEvents(25)

      logEditorDebug('Vue', 'error', {
        info,
        component: instance?.type?.name ?? null,
        route: router.currentRoute.value.fullPath,
        error: errorSummary,
        recentEvents,
      })

      console.error('[EditorDebug] Vue error', {
        info,
        component: instance?.type?.name ?? null,
        route: router.currentRoute.value.fullPath,
        error: errorSummary,
        recentEvents,
      })
    }
  }

  // Directive to disable WebKit autocorrect/autocapitalize/spellcheck on inputs
  app.directive('no-autocorrect', {
    mounted(el) {
      el.setAttribute('autocorrect', 'off')
      el.setAttribute('autocapitalize', 'off')
      el.spellcheck = false
    }
  })

  app.mount('#app')
}).catch((error) => {
  console.error('Failed to initialize API config:', error)
  const errorMessage = error?.message || (typeof error === 'string' ? error : JSON.stringify(error))
  showError(errorMessage)
})
