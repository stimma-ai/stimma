/**
 * Forward browser console output to the Tauri app log.
 */

const levels = ['log', 'info', 'warn', 'error', 'debug']

const originalConsole = {
  log: console.log.bind(console),
  info: console.info.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
  debug: console.debug.bind(console),
}

let initialized = false

function isTauri() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

function formatArg(arg) {
  if (arg === null) return 'null'
  if (arg === undefined) return 'undefined'
  if (arg instanceof Error) {
    return `${arg.name}: ${arg.message}${arg.stack ? `\n${arg.stack}` : ''}`
  }
  if (typeof arg === 'object') {
    try {
      return JSON.stringify(arg, null, 2)
    } catch {
      return String(arg)
    }
  }
  return String(arg)
}

function formatArgs(args) {
  return args.map(formatArg).join(' ')
}

async function sendToTauri(level, message) {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('log_from_webview', { level, message })
  } catch {
    // Logging must never break the app.
  }
}

function createInterceptor(level) {
  return (...args) => {
    originalConsole[level](...args)
    if (isTauri()) {
      void sendToTauri(level, formatArgs(args))
    }
  }
}

export function initConsoleBridge() {
  if (initialized || !isTauri()) return
  initialized = true

  for (const level of levels) {
    console[level] = createInterceptor(level)
  }

  window.addEventListener('error', (event) => {
    const message = event.error
      ? formatArgs([event.error])
      : `${event.message} at ${event.filename}:${event.lineno}:${event.colno}`
    void sendToTauri('error', `[Global Error] ${message}`)
  })

  window.addEventListener('unhandledrejection', (event) => {
    void sendToTauri('error', `[Unhandled Promise Rejection] ${formatArgs([event.reason])}`)
  })

  console.info('[console-bridge] Initialized - web console output will be logged to app logs')
}

export function installVueConsoleHandlers(app) {
  if (!isTauri()) return

  const previousErrorHandler = app.config.errorHandler
  const previousWarnHandler = app.config.warnHandler

  app.config.errorHandler = (err, instance, info) => {
    const componentName = instance?.$options?.name || instance?.$options?.__name || instance?.type?.name || 'Anonymous'
    void sendToTauri('error', `[Vue Error in ${componentName}] ${info}\n${formatArgs([err])}`)
    if (previousErrorHandler) {
      previousErrorHandler(err, instance, info)
    } else {
      originalConsole.error(err)
    }
  }

  app.config.warnHandler = (msg, instance, trace) => {
    const componentName = instance?.$options?.name || instance?.$options?.__name || instance?.type?.name || 'Anonymous'
    void sendToTauri('warn', `[Vue warn in ${componentName}] ${msg}${trace ? `\n${trace}` : ''}`)
    if (previousWarnHandler) {
      previousWarnHandler(msg, instance, trace)
    } else {
      originalConsole.warn(msg, trace)
    }
  }
}

export function restoreConsoleBridge() {
  for (const level of levels) {
    console[level] = originalConsole[level]
  }
  initialized = false
}
