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
import { waitForProxyPort } from './proxy'
import {
  LOCAL_DEVICE,
  connect as connectDevice,
  getActiveDeviceId,
  getConnectionState,
  forgetDevice,
  getKnownDevices,
  localAuth,
  localStatus,
  refreshDevices,
  renameLocal,
  setActiveDevice,
  setLocalServing,
  useLocalServer,
} from './devices'
import {
  relaunchApp,
  updaterCheck,
  updaterClose,
  updaterDownload,
  updaterDownloadAndInstall,
  updaterInstall,
} from './updater'
import {
  helperCall,
  helperRequest,
  removeEventListener,
} from './helper'
import { getLegacyStorageDump, markLegacyStorageImported } from './legacyStorage'
import { log } from './log'
import {
  closeDeletedProfileWindow,
  getWindowRegistry,
  isAppUrl,
  labelOf,
  openProfileWindow,
  reloadAllWindows,
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
  // ---- legacy storage import (sync: preload blocks on this pre-page-load) --
  // Not part of the contextBridge surface; the preload consumes it directly.
  ipcMain.on('stimma:legacy-storage-dump', (event) => {
    event.returnValue = getLegacyStorageDump()
  })
  ipcMain.on('stimma:legacy-storage-imported', (_event, keysWritten: unknown) => {
    markLegacyStorageImported(typeof keysWritten === 'number' ? keysWritten : 0)
  })

  // ---- app / backend -------------------------------------------------------
  // The renderer talks to the proxy, never to the backend directly. Still
  // gated on the backend port so boot semantics are unchanged: resolving
  // early would just hand back a proxy that 503s until the target is set.
  handle('stimma:get-backend-port', async () => {
    await waitForBackendPort()
    return waitForProxyPort()
  })

  // ---- multi-device --------------------------------------------------------
  // The renderer never talks to a remote device itself; it asks main to point
  // the proxy somewhere and then reloads against the same local origin.

  handle('stimma:md-get-state', async () => ({
    activeDeviceId: getActiveDeviceId(),
    connectionState: getConnectionState(),
    devices: getKnownDevices(),
    localDeviceId: LOCAL_DEVICE,
  }))

  handle('stimma:md-refresh-devices', async () => refreshDevices())

  // Deliberately NOT proxied: these describe and control the machine the user
  // is sitting at, even while the window is driving another one.
  handle('stimma:md-local-status', async () => localStatus())

  // Account sign-in/out is part of the same local island: it is about this
  // install, never the device the window is on. Restricted to /auth/* so the
  // renderer cannot turn this into a general bypass of the proxy.
  handle('stimma:auth-local', async (_event, method: unknown, pathname: unknown, body: unknown) => {
    if (method !== 'GET' && method !== 'POST') throw new Error('method must be GET or POST')
    if (typeof pathname !== 'string' || !pathname.startsWith('/auth/')) {
      throw new Error('path must be under /auth/')
    }
    // Same gate as get-backend-port: the answer is about the local install,
    // so wait for it rather than reporting "signed out" while it boots.
    await waitForBackendPort()
    return localAuth(method, pathname, body ?? undefined)
  })

  handle('stimma:md-set-local-serving', async (_event, enabled: unknown) => {
    if (typeof enabled !== 'boolean') throw new Error('enabled must be a boolean')
    return setLocalServing(enabled)
  })

  handle('stimma:md-rename-local', async (_event, name: unknown) => {
    if (typeof name !== 'string' || !name.trim()) throw new Error('name required')
    return renameLocal(name.trim())
  })

  handle('stimma:md-forget-device', async (_event, deviceId: unknown) => {
    if (typeof deviceId !== 'string' || !deviceId) throw new Error('deviceId required')
    await forgetDevice(deviceId)
  })

  handle('stimma:md-set-active-device', async (_event, deviceId: unknown) => {
    if (typeof deviceId !== 'string' || !deviceId) throw new Error('deviceId required')
    const state = await setActiveDevice(deviceId)
    // Switching is explicitly allowed to be heavyweight: reloading is what
    // resets the renderer's module-scoped state for the new device.
    if (state === 'ready') reloadAllWindows()
    return state
  })

  handle('stimma:md-use-local-server', async () => {
    const state = await useLocalServer()
    if (state === 'ready') reloadAllWindows()
    return state
  })

  handle('stimma:md-retry', async () => {
    const state = await connectDevice()
    // A window that booted unreachable skipped its backend-dependent startup
    // (profile resolution, route restore), so recovering has to be a reload
    // rather than a resumption.
    if (state === 'ready') reloadAllWindows()
    return state
  })

  handle('stimma:get-app-version', () => app.getVersion())

  handle('stimma:relaunch', () => {
    relaunchApp()
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

  handle('stimma:embed-metadata', async (_event, req: unknown) => {
    if (req === null || typeof req !== 'object') throw new Error('Invalid embed request')
    const result = await helperRequest('embed_metadata', req)
    return typeof result === 'string' && result.length > 0 ? result : null
  })

  handle('stimma:is-shift-key-down', () => false)

  // ---- voice (stimma-native helper) ----------------------------------------
  handle('stimma:voice-model-status', () => helperRequest('voice_model_status'))

  handle('stimma:voice-download-model', (event) => {
    const target = event.sender
    return helperRequest('voice_download_model', {}, (payload) => {
      if (!target.isDestroyed()) target.send('stimma:voice-download-event', payload)
    })
  })

  // One live dictation session; owned by the window that started it. The
  // transcript stream outlives the voice_start response and is torn down on
  // stop/cancel, owner destruction, or (helper-side) lease expiry.
  let voiceSession: { requestId: number; ownerDestroyed: () => void } | null = null
  const endVoiceSession = () => {
    if (!voiceSession) return
    removeEventListener(voiceSession.requestId)
    voiceSession = null
  }

  handle('stimma:voice-start', async (event) => {
    endVoiceSession()
    const target = event.sender
    const call = helperCall(
      'voice_start',
      {},
      (payload) => {
        if (!target.isDestroyed()) target.send('stimma:voice-transcript-event', payload)
      },
      'explicit',
    )
    const ownerDestroyed = () => {
      // Renderer went away mid-capture: cancel immediately rather than
      // waiting for the helper's keepalive lease to expire.
      void helperRequest('voice_cancel').catch(() => {})
      endVoiceSession()
    }
    target.once('destroyed', ownerDestroyed)
    voiceSession = { requestId: call.id, ownerDestroyed }
    await call.result
  })

  handle('stimma:voice-stop', async () => {
    const text = await helperRequest('voice_stop')
    endVoiceSession()
    return text
  })

  handle('stimma:voice-cancel', async () => {
    await helperRequest('voice_cancel')
    endVoiceSession()
  })

  handle('stimma:voice-keepalive', () => helperRequest('voice_keepalive'))

  // ---- updater -------------------------------------------------------------
  handle('stimma:updater-check', () => updaterCheck())
  handle('stimma:updater-download', () => updaterDownload())
  handle('stimma:updater-install', () => updaterInstall())
  handle('stimma:updater-download-and-install', () => updaterDownloadAndInstall())
  handle('stimma:updater-close', () => updaterClose())

  // Second-instance / tray helpers reuse this too.
  void showAllWindows
}
