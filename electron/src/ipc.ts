/**
 * IPC surface backing the preload bridge. Every handler validates the sender
 * (top-level app frame only) and treats renderer input as untrusted.
 */

import {
  BrowserWindow,
  IpcMainInvokeEvent,
  app,
  clipboard,
  dialog,
  ipcMain,
  shell,
} from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import { waitForBackendPort } from './backend'
import { log } from './log'
import {
  closeDeletedProfileWindow,
  getWindowRegistry,
  isAppUrl,
  labelOf,
  openProfileWindow,
  showAllWindows,
} from './windows'

function senderWindow(event: IpcMainInvokeEvent): BrowserWindow {
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!win) throw new Error('IPC from unknown sender')
  return win
}

function validateSender(event: IpcMainInvokeEvent): void {
  const frame = event.senderFrame
  if (!frame || frame.parent !== null) {
    throw new Error('IPC allowed only from the top-level app frame')
  }
  if (!isAppUrl(frame.url)) {
    throw new Error('IPC from unexpected origin')
  }
}

function handle(
  channel: string,
  handler: (event: IpcMainInvokeEvent, ...args: any[]) => unknown,
): void {
  ipcMain.handle(channel, (event, ...args) => {
    validateSender(event)
    return handler(event, ...args)
  })
}

function requireString(value: unknown, what: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`Invalid ${what}`)
  }
  return value
}

const EXTERNAL_URL_SCHEMES = new Set(['http:', 'https:', 'mailto:', 'x-apple.systempreferences:'])

function requireExternalUrl(value: unknown, schemes: Set<string>): string {
  const raw = requireString(value, 'URL')
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    throw new Error('Invalid external URL')
  }
  if (!schemes.has(parsed.protocol)) {
    throw new Error(`URL scheme not allowed: ${parsed.protocol}`)
  }
  return parsed.toString()
}

function requireAbsolutePath(value: unknown): string {
  const raw = requireString(value, 'path')
  if (!path.isAbsolute(raw)) throw new Error('Path must be absolute')
  return raw
}

async function uniqueDownloadPath(filename: string): Promise<string> {
  const downloads = app.getPath('downloads')
  // Constrain writes to the Downloads root: base name only, no traversal.
  const base = path.basename(filename)
  if (!base || base === '.' || base === '..') throw new Error('Invalid filename')

  const exists = (p: string) => fs.promises.access(p).then(() => true, () => false)
  if (!(await exists(path.join(downloads, base)))) return path.join(downloads, base)

  const lastDot = base.lastIndexOf('.')
  const name = lastDot > 0 ? base.slice(0, lastDot) : base
  const ext = lastDot > 0 ? base.slice(lastDot) : ''
  for (let counter = 1; counter < 1000; counter++) {
    const candidate = path.join(downloads, `${name} (${counter})${ext}`)
    if (!(await exists(candidate))) return candidate
  }
  return path.join(downloads, `${name}_${Date.now()}${ext}`)
}

export function registerIpcHandlers(): void {
  // ---- app / backend -------------------------------------------------------
  handle('stimma:get-backend-port', () => waitForBackendPort())

  handle('stimma:get-app-version', () => app.getVersion())

  handle('stimma:relaunch', () => {
    app.relaunch()
    app.exit(0)
  })

  handle('stimma:log', (_event, level: unknown, message: unknown) => {
    const lvl = typeof level === 'string' ? level : 'info'
    const msg = typeof message === 'string' ? message : String(message)
    if (lvl === 'error') log.error('web', msg)
    else if (lvl === 'warn') log.warn('web', msg)
    else if (lvl === 'debug') log.debug('web', msg)
    else log.info('web', msg)
  })

  // ---- windows / profiles --------------------------------------------------
  handle('stimma:get-window-profile', (event) =>
    getWindowRegistry().profileFor(labelOf(senderWindow(event))),
  )

  handle('stimma:report-window-profile', (event, profileId: unknown) => {
    getWindowRegistry().setProfile(
      labelOf(senderWindow(event)),
      requireString(profileId, 'profile id'),
    )
  })

  handle('stimma:open-profile-window', (_event, profileId: unknown) => {
    openProfileWindow(requireString(profileId, 'profile id'))
  })

  handle('stimma:close-deleted-profile-window', (event) =>
    closeDeletedProfileWindow(senderWindow(event)),
  )

  handle('stimma:close-current-window', (event) => {
    senderWindow(event).close()
  })

  handle('stimma:set-window-title', (event, title: unknown) => {
    senderWindow(event).setTitle(requireString(title, 'title'))
  })

  handle('stimma:set-window-size', (event, width: unknown, height: unknown) => {
    if (typeof width !== 'number' || typeof height !== 'number') {
      throw new Error('Invalid window size')
    }
    const w = Math.round(width)
    const h = Math.round(height)
    if (w < 100 || h < 100 || w > 20000 || h > 20000) throw new Error('Invalid window size')
    senderWindow(event).setSize(w, h)
  })

  handle('stimma:focus-current-window', (event) => {
    const win = senderWindow(event)
    win.show()
    if (win.isMinimized()) win.restore()
    win.focus()
  })

  // ---- shell ---------------------------------------------------------------
  handle('stimma:open-external', async (_event, url: unknown) => {
    await shell.openExternal(requireExternalUrl(url, EXTERNAL_URL_SCHEMES))
  })

  handle('stimma:open-auth-url', async (_event, url: unknown) => {
    // Hardened variant: http(s) only (mirrors the Rust open_external_url).
    await shell.openExternal(requireExternalUrl(url, new Set(['http:', 'https:'])))
  })

  handle('stimma:open-path', async (_event, target: unknown) => {
    const error = await shell.openPath(requireAbsolutePath(target))
    if (error) throw new Error(error)
  })

  handle('stimma:reveal-item', (_event, target: unknown) => {
    shell.showItemInFolder(requireAbsolutePath(target))
  })

  // ---- clipboard -----------------------------------------------------------
  handle('stimma:clipboard-write-text', (_event, text: unknown) => {
    clipboard.writeText(typeof text === 'string' ? text : String(text))
  })

  // ---- dialogs -------------------------------------------------------------
  handle('stimma:pick-directory', async (event, options: unknown) => {
    const opts = (options ?? {}) as { title?: unknown; defaultPath?: unknown }
    const result = await dialog.showOpenDialog(senderWindow(event), {
      properties: ['openDirectory', 'createDirectory'],
      title: typeof opts.title === 'string' ? opts.title : undefined,
      defaultPath: typeof opts.defaultPath === 'string' ? opts.defaultPath : undefined,
    })
    return result.canceled ? null : result.filePaths[0] ?? null
  })

  // ---- downloads -----------------------------------------------------------
  handle('stimma:save-to-downloads', async (_event, filename: unknown, data: unknown) => {
    const name = requireString(filename, 'filename')
    if (!(data instanceof Uint8Array)) throw new Error('Invalid file data')
    const target = await uniqueDownloadPath(name)
    await fs.promises.writeFile(target, data)
    log.info('stimma', `Saved download: ${target}`)
    return true
  })

  // ---- print ---------------------------------------------------------------
  handle('stimma:print', (event) => {
    senderWindow(event).webContents.print()
  })

  // ---- drag-out ------------------------------------------------------------
  handle('stimma:start-native-drag', (event, items: unknown, previewImage: unknown) => {
    if (!Array.isArray(items) || items.length === 0) throw new Error('Invalid drag items')
    const files = items.map((item) => requireAbsolutePath(item))
    const icon = typeof previewImage === 'string' && previewImage ? previewImage : files[0]
    event.sender.startDrag(
      files.length === 1 ? { file: files[0], icon } : ({ files, icon } as any),
    )
  })

  handle('stimma:embed-metadata', () => {
    // Metadata embedding moves to the stimma-native helper in Phase 4; until
    // then drags fall back to the raw file (frontend handles null).
    return null
  })

  handle('stimma:is-shift-key-down', () => false)

  // ---- voice (stimma-native helper lands in Phase 4) -----------------------
  handle('stimma:voice-model-status', () => false)
  handle('stimma:voice-download-model', () => {
    throw new Error('Voice input is not available in the Electron shell yet')
  })
  handle('stimma:voice-start', () => {
    throw new Error('Voice input is not available in the Electron shell yet')
  })
  handle('stimma:voice-stop', () => '')
  handle('stimma:voice-cancel', () => {})
  handle('stimma:voice-keepalive', () => {})

  // ---- updater (electron-updater lands in Phase 6) -------------------------
  handle('stimma:updater-check', () => null)
  handle('stimma:updater-download', () => {
    throw new Error('Updater not wired yet')
  })
  handle('stimma:updater-install', () => {
    throw new Error('Updater not wired yet')
  })
  handle('stimma:updater-download-and-install', () => {
    throw new Error('Updater not wired yet')
  })
  handle('stimma:updater-close', () => {})

  // Second-instance / tray helpers reuse this too.
  void showAllWindows
}
