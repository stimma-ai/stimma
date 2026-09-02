/**
 * Window management: creation, browser-style close semantics, and the
 * profile-window registry ported from src-tauri/src/windows.rs.
 *
 * Semantics: each open window is pinned to one profile; switching profiles
 * focuses (or opens) that profile's window; the set of open windows persists
 * so relaunch restores them. Closing one of several windows destroys it and
 * drops it from the restore set; closing the last hides it so the backend
 * stays warm; a genuine quit leaves the registry intact.
 */

import { BrowserWindow, app } from 'electron'
import path from 'node:path'
import { log } from './log'
import { WindowRegistry, profileWindowLabel } from './registry'
import { storedBoundsFor, trackWindowState } from './windowState'

let quitting = false

export function markQuitting(): void {
  quitting = true
}

export function isQuitting(): boolean {
  return quitting
}

export interface WindowEnvironment {
  devUrl: string | null
  /** Packaged mode: app:// origin served by the main-process protocol handler. */
  appOrigin: string | null
}

let environment: WindowEnvironment = { devUrl: null, appOrigin: null }
let registry: WindowRegistry | null = null

export function setWindowEnvironment(env: WindowEnvironment): void {
  environment = env
}

export function setWindowRegistry(reg: WindowRegistry): void {
  registry = reg
}

export function getWindowRegistry(): WindowRegistry {
  if (!registry) throw new Error('Window registry not initialized')
  return registry
}

function preloadPath(): string {
  return path.join(__dirname, 'preload.cjs')
}

export function labelOf(win: BrowserWindow): string {
  return (win as any).stimmaLabel ?? 'main'
}

export function windowForLabel(label: string): BrowserWindow | null {
  return (
    BrowserWindow.getAllWindows().find(
      (win) => !win.isDestroyed() && labelOf(win) === label,
    ) ?? null
  )
}

let windowTitle = 'Stimma'

export function setWindowTitlePrefix(title: string): void {
  windowTitle = title
}

export function createAppWindow(label: string): BrowserWindow {
  const stored = storedBoundsFor(label)
  const win = new BrowserWindow({
    title: windowTitle,
    width: stored?.width ?? 1200,
    height: stored?.height ?? 800,
    ...(stored ? { x: stored.x, y: stored.y } : {}),
    minWidth: 1024,
    minHeight: 640,
    show: true,
    // Tauri config: titleBarStyle Overlay + hiddenTitle — traffic lights over
    // app content on macOS; standard frame elsewhere.
    ...(process.platform === 'darwin'
      ? { titleBarStyle: 'hiddenInset' as const }
      : {}),
    webPreferences: {
      preload: preloadPath(),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  })

  ;(win as any).stimmaLabel = label
  if (stored?.maximized) win.maximize()
  if (stored?.fullscreen) win.setFullScreen(true)
  trackWindowState(label, win)

  // Browser-style close semantics (mirrors the Tauri on_window_event
  // handler): closing one of several profile windows destroys it and drops
  // it from the restore set; closing the last hides it instead so the
  // backend stays warm. A genuine quit bypasses both and leaves the
  // registry intact for session restore.
  win.on('close', (event) => {
    if (quitting) return
    const openWindows = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed())
    if (openWindows.length > 1) {
      registry?.remove(label)
    } else {
      event.preventDefault()
      win.hide()
    }
  })

  // Deny renderer-initiated navigation away from the app and any new-window
  // creation; external links go through the bridge's openExternal.
  win.webContents.setWindowOpenHandler(({ url }) => {
    log.warn('security', `Blocked window.open to ${url}`)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    if (!isAppUrl(url)) {
      log.warn('security', `Blocked navigation to ${url}`)
      event.preventDefault()
    }
  })

  // Renderer failure diagnostics — these are the only signals a packaged
  // build has when the page never comes up.
  win.webContents.on('did-fail-load', (_e, code, description, url) => {
    log.error('stimma', `Renderer failed to load ${url}: ${description} (${code})`)
  })
  win.webContents.on('preload-error', (_e, preloadPathValue, error) => {
    log.error('stimma', `Preload error in ${preloadPathValue}: ${error}`)
  })
  win.webContents.on('render-process-gone', (_e, details) => {
    log.error('stimma', `Renderer gone: ${details.reason} (exit ${details.exitCode})`)
  })
  // Raw renderer console (Chromium-level). The console bridge forwards app
  // logs once it initializes; this catches everything before/without it.
  win.webContents.on('console-message', (event: any, ...legacy: any[]) => {
    const message = event?.message ?? legacy[1]
    const source = event?.sourceId ?? legacy[3]
    const line = event?.lineNumber ?? legacy[2]
    const level = event?.level ?? legacy[0]
    if (level === 'error' || level === 'warning' || (typeof level === 'number' && level >= 2)) {
      log.warn('renderer', `${message} (${source}:${line})`)
    }
  })
  win.webContents.on('did-finish-load', () => {
    log.info('stimma', `Renderer finished loading ${win.webContents.getURL()}`)
  })

  if (environment.devUrl) {
    void win.loadURL(environment.devUrl)
  } else if (environment.appOrigin) {
    void win.loadURL(environment.appOrigin + '/')
  } else {
    log.error('stimma', 'No frontend source configured (devUrl or appOrigin)')
  }

  return win
}

/**
 * Recreate the windows that were open when the app last quit (browser-style
 * session restore). First launch — or a missing registry — falls back to the
 * single bootstrap "main" window, whose profile the frontend resolves and
 * reports back.
 */
export function restoreWindows(): void {
  const reg = getWindowRegistry()
  let entries = reg.snapshot()
  if (entries.length === 0) {
    entries = [{ label: 'main', profile_id: null }]
    reg.replace(entries)
  }
  for (const entry of entries) {
    if (!windowForLabel(entry.label)) {
      createAppWindow(entry.label)
    }
  }
}

function focusWindow(win: BrowserWindow): void {
  win.show()
  if (win.isMinimized()) win.restore()
  win.focus()
}

/**
 * Browser-style profile switch: focus the profile's window if one is open,
 * otherwise open a new window pinned to it. (Port of open_profile_window.)
 */
export function openProfileWindow(profileId: string): void {
  const reg = getWindowRegistry()

  const existingLabel = reg.labelForProfile(profileId)
  if (existingLabel) {
    const existing = windowForLabel(existingLabel)
    if (existing) {
      focusWindow(existing)
      return
    }
    reg.remove(existingLabel)
  }

  const label = profileWindowLabel(profileId)
  const open = windowForLabel(label)
  if (open) {
    reg.setProfile(label, profileId)
    focusWindow(open)
    return
  }

  reg.setProfile(label, profileId)
  try {
    createAppWindow(label)
  } catch (error) {
    reg.remove(label)
    throw error
  }
}

/**
 * Close a window because its profile no longer exists. Returns false when it
 * is the last window — the caller falls back to another profile in place.
 */
export function closeDeletedProfileWindow(win: BrowserWindow): boolean {
  const openWindows = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed())
  if (openWindows.length <= 1) return false
  getWindowRegistry().remove(labelOf(win))
  // Defer the destroy one tick so the IPC response reaches the caller before
  // its renderer dies.
  setImmediate(() => {
    if (!win.isDestroyed()) win.destroy()
  })
  return true
}

export function isAppUrl(url: string): boolean {
  if (environment.devUrl && url.startsWith(environment.devUrl)) return true
  if (environment.appOrigin && url.startsWith(environment.appOrigin)) return true
  return false
}

/**
 * Push connection state to every window. The renderer treats it as ordinary
 * app state (connecting | ready | unreachable) rather than a boot condition,
 * which is what lets one component cover cold launch, satellite launch, and
 * a mid-session drop.
 */
export function broadcastConnectionState(state: string): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed()) continue
    win.webContents.send('stimma:connection-state', state)
  }
}

/**
 * Reload every window from the app root — used after a device switch or a
 * successful retry. Not `webContents.reload()`: that keeps the current URL,
 * and a pass that ran against an unreachable or half-up backend may have
 * parked the window on a route (onboarding, say) that the new device has no
 * business inheriting. Starting from '/' lets route restore decide instead.
 */
export function reloadAllWindows(): void {
  const rootUrl = environment.devUrl ?? (environment.appOrigin ? environment.appOrigin + '/' : null)
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed()) continue
    if (rootUrl) void win.loadURL(rootUrl)
    else win.webContents.reload()
  }
}

export function showAllWindows(): void {
  const windows = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed())
  for (const win of windows) {
    win.show()
    if (win.isMinimized()) win.restore()
  }
  windows[0]?.focus()
}

export function installAppLifecycle(): void {
  app.on('before-quit', () => {
    markQuitting()
  })

  // macOS keeps the app alive with no windows (like Music.app); other
  // platforms keep running too because the last window only hides.
  app.on('window-all-closed', () => {
    if (quitting) app.quit()
  })

  // Dock icon click with hidden windows re-shows them.
  app.on('activate', () => {
    showAllWindows()
  })
}
