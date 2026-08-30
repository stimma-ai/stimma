/**
 * Per-label window bounds persistence (replaces tauri-plugin-window-state).
 * Visibility is deliberately NOT persisted: closing the last window hides it,
 * and persisting hidden state could relaunch the app with no visible window.
 */

import { BrowserWindow, screen } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

interface StoredBounds {
  x: number
  y: number
  width: number
  height: number
  maximized?: boolean
  fullscreen?: boolean
}

let filePath = ''
let states: Record<string, StoredBounds> = {}

export function initWindowState(dataDir: string): void {
  filePath = path.join(dataDir, 'window-state.json')
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    if (parsed && typeof parsed === 'object') states = parsed
  } catch {
    states = {}
  }
}

function persist(): void {
  if (!filePath) return
  try {
    const tmp = filePath + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(states, null, 2))
    fs.renameSync(tmp, filePath)
  } catch {
    // Best-effort.
  }
}

/** Bounds for a label if they are (still) on a connected display. */
export function storedBoundsFor(label: string): StoredBounds | null {
  const bounds = states[label]
  if (!bounds || typeof bounds.width !== 'number' || typeof bounds.height !== 'number') {
    return null
  }
  const visible = screen.getAllDisplays().some((display) => {
    const area = display.workArea
    return (
      bounds.x < area.x + area.width &&
      bounds.x + bounds.width > area.x &&
      bounds.y < area.y + area.height &&
      bounds.y + bounds.height > area.y
    )
  })
  return visible ? bounds : null
}

export function trackWindowState(label: string, win: BrowserWindow): void {
  let timer: NodeJS.Timeout | null = null
  const save = () => {
    if (win.isDestroyed()) return
    const maximized = win.isMaximized()
    const fullscreen = win.isFullScreen()
    // Normal bounds only — restoring a maximized window re-maximizes from them.
    const bounds = maximized || fullscreen ? win.getNormalBounds() : win.getBounds()
    states[label] = { ...bounds, maximized, fullscreen }
    persist()
  }
  const debounced = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(save, 400)
  }
  win.on('resize', debounced)
  win.on('move', debounced)
  win.on('close', save)
}
