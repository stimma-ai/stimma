/**
 * Window management: creation, close semantics, and (in Phase 3) the
 * profile-window registry ported from src-tauri/src/windows.rs.
 *
 * Phase 2 scope: a single "main" window with the browser-style lifecycle —
 * closing the last window hides it (backend stays warm), Cmd-Q genuinely
 * quits, Dock reactivation re-shows.
 */

import { BrowserWindow, app } from 'electron'
import path from 'node:path'
import { log } from './log'

let quitting = false

export function markQuitting(): void {
  quitting = true
}

export function isQuitting(): boolean {
  return quitting
}

export interface WindowEnvironment {
  devUrl: string | null
  frontendDist: string | null
}

let environment: WindowEnvironment = { devUrl: null, frontendDist: null }

export function setWindowEnvironment(env: WindowEnvironment): void {
  environment = env
}

function preloadPath(): string {
  return path.join(__dirname, 'preload.cjs')
}

export function createAppWindow(label: string): BrowserWindow {
  const win = new BrowserWindow({
    title: 'Stimma',
    width: 1200,
    height: 800,
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

  // Browser-style close semantics: closing one of several windows destroys
  // it; closing the last window hides it so the backend stays warm. A real
  // quit (Cmd-Q / explicit quit) bypasses the hide.
  win.on('close', (event) => {
    if (quitting) return
    const openWindows = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed())
    if (openWindows.length <= 1) {
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

  if (environment.devUrl) {
    void win.loadURL(environment.devUrl)
  } else if (environment.frontendDist) {
    void win.loadFile(path.join(environment.frontendDist, 'index.html'))
  } else {
    log.error('stimma', 'No frontend source configured (devUrl or frontendDist)')
  }

  return win
}

export function isAppUrl(url: string): boolean {
  if (environment.devUrl && url.startsWith(environment.devUrl)) return true
  if (url.startsWith('file://')) return true
  return false
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
