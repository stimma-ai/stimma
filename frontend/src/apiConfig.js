/**
 * API Configuration for Stimma
 *
 * In development: Uses relative /api paths (Vite proxy handles it)
 * In Tauri production: Uses dynamic port from sidecar
 */
import axios from 'axios'
import { waitForBackendHealth } from './utils/backendStartup'

let apiBaseUrl = '/api'
let wsBaseUrl = '/ws'
let backendOrigin = '' // Empty for dev (relative URLs), 'http://127.0.0.1:PORT' for Tauri
let initialized = false
let initPromise = null
let updateStartupStatus = null

const SESSION_HEADER = 'X-Stimma-Session-Id'

// Session id ownership: a plain UUID minted at app start and rotated after
// 30 minutes of inactivity. Sent as X-Stimma-Session-Id on every sidecar
// request; the backend stamps it onto telemetry batches.
const SESSION_IDLE_ROTATE_MS = 30 * 60 * 1000

function newSessionId() {
  try {
    return crypto.randomUUID()
  } catch {
    // Fallback for environments without crypto.randomUUID
    return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`
  }
}

let sessionId = newSessionId()
let lastActivityAt = Date.now()

function isSidecarUrl(url) {
  if (typeof url !== 'string') return false
  if (url.startsWith('/')) return true
  if (backendOrigin && url.startsWith(backendOrigin)) return true
  return false
}

function currentSessionId() {
  const now = Date.now()
  if (now - lastActivityAt > SESSION_IDLE_ROTATE_MS) {
    sessionId = newSessionId()
  }
  lastActivityAt = now
  return sessionId
}

/**
 * The current app session id (rotated on app start + 30 min inactivity).
 */
export function getSessionId() {
  return currentSessionId()
}

function installSessionHeaderInterceptors() {
  // Axios — covers all axios.* call sites across the app.
  axios.interceptors.request.use((config) => {
    const url = config.url || ''
    const isAbsolute = /^https?:/i.test(url)
    const fullUrl = isAbsolute ? url : `${config.baseURL || ''}${url}`
    if (isSidecarUrl(fullUrl)) {
      const sid = currentSessionId()
      if (sid) {
        config.headers = config.headers || {}
        if (!config.headers[SESSION_HEADER]) {
          config.headers[SESSION_HEADER] = sid
        }
      }
    }
    return config
  })

  // window.fetch — covers all `fetch('/api/...')` call sites. Wrap once.
  if (typeof window === 'undefined' || !window.fetch) return
  if (window.__stimmaFetchSessionPatched) return
  window.__stimmaFetchSessionPatched = true
  const originalFetch = window.fetch.bind(window)
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url
    if (isSidecarUrl(url)) {
      const sid = currentSessionId()
      if (sid) {
        const headers = new Headers(
          init.headers || (typeof input !== 'string' ? input?.headers : undefined),
        )
        if (!headers.has(SESSION_HEADER)) {
          headers.set(SESSION_HEADER, sid)
          init = { ...init, headers }
        }
      }
    }
    return originalFetch(input, init)
  }
}

installSessionHeaderInterceptors()

/**
 * Set a callback to receive startup status updates
 */
export function setStartupStatusCallback(callback) {
  updateStartupStatus = callback
}

/**
 * Check if running in Tauri environment
 */
export function isTauri() {
  return typeof window !== 'undefined' && window.__TAURI_INTERNALS__ !== undefined
}

/**
 * Initialize the API configuration.
 * Must be called before any API requests in Tauri mode.
 */
export async function initApiConfig() {
  if (initialized) return
  if (initPromise) return initPromise

  initPromise = (async () => {
    if (isTauri()) {
      console.log('[apiConfig] Tauri detected, getting port...')
      const tauriCore = await import('@tauri-apps/api/core')
      const { invoke } = tauriCore

      // Step 1: Get the port from Tauri (retry up to 30 seconds)
      updateStartupStatus?.('Starting backend...')
      const maxAttempts = 60
      const delayMs = 500
      let port = null

      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
          port = await invoke('get_backend_port')
          console.log('[apiConfig] Got port:', port)
          break
        } catch (error) {
          console.log('[apiConfig] Waiting for port, attempt', attempt, error)
          if (attempt >= maxAttempts) {
            throw new Error('Please try restarting the app')
          }
          await new Promise(resolve => setTimeout(resolve, delayMs))
        }
      }

      backendOrigin = `http://127.0.0.1:${port}`
      apiBaseUrl = `${backendOrigin}/api`
      wsBaseUrl = `ws://127.0.0.1:${port}/ws`
      axios.defaults.baseURL = backendOrigin

      // Step 2: Wait for backend to be ready (health check). Once the native
      // supervisor has supplied a port, there is deliberately no fixed
      // readiness deadline: a large one-time migration can legitimately take
      // several minutes and remains transactional until startup completes.
      updateStartupStatus?.('Waiting for backend...')
      console.log('[apiConfig] Health checking', backendOrigin)
      const response = await waitForBackendHealth(backendOrigin, {
        retryDelayMs: delayMs,
        onWaiting: ({ attempt, elapsedMs }) => {
          if (attempt === 1 || attempt % 20 === 0) {
            console.log(
              '[apiConfig] Backend is still initializing',
              Math.round(elapsedMs / 1000),
              'seconds elapsed',
            )
          }
          updateStartupStatus?.(
            elapsedMs >= 30_000
              ? 'Upgrading your library. Large libraries may take several minutes.'
              : 'Preparing your library...',
          )
        },
      })
      console.log('[apiConfig] Health check response:', response.status)
      updateStartupStatus?.('Ready')
      initialized = true
      return
    } else {
      // Development mode - use relative paths (Vite proxy handles routing)
      console.log('[apiConfig] Dev mode: using relative /api paths')
    }
    initialized = true
  })()

  return initPromise
}

/**
 * Get the API base URL.
 * In dev mode: '/api'
 * In Tauri mode: 'http://127.0.0.1:PORT/api'
 */
export function getApiBase() {
  return apiBaseUrl
}

/**
 * Get the WebSocket base URL.
 * In dev mode: '/ws'
 * In Tauri mode: 'ws://127.0.0.1:PORT/ws'
 */
export function getWsBase() {
  return wsBaseUrl
}

/**
 * Check if API config has been initialized
 */
export function isInitialized() {
  return initialized
}

/**
 * Get the backend origin.
 * In dev mode: '' (empty, use relative URLs)
 * In Tauri mode: 'http://127.0.0.1:PORT'
 */
export function getBackendOrigin() {
  return backendOrigin
}

/**
 * Rewrite a URL for the current environment.
 * In dev mode: returns URL unchanged
 * In Tauri mode: prepends the backend origin to relative /api URLs
 */
export function rewriteUrl(url) {
  if (!backendOrigin) return url
  if (typeof url !== 'string') return url
  if (url.startsWith('/api') || url.startsWith('/ws')) {
    return backendOrigin + url
  }
  return url
}
