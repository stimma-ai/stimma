/**
 * Tauri implementation of the desktop bridge.
 *
 * The ONLY place (besides bootstrap glue) allowed to import `@tauri-apps/*`
 * or inspect `__TAURI_INTERNALS__`. All imports stay dynamic so the browser
 * build never loads Tauri modules.
 */

import type {
  DesktopBridge,
  DesktopUpdate,
  LocalDeviceStatus,
  DirectoryPickerOptions,
  VoiceDownloadEvent,
  VoiceTranscriptEvent,
} from './types'
import { fetchLocalAuth } from './browserBridge.ts'

export function isTauriShell(): boolean {
  return typeof window !== 'undefined' && (window as any).__TAURI_INTERNALS__ !== undefined
}

async function core() {
  return import('@tauri-apps/api/core')
}

async function currentWindow() {
  const { getCurrentWindow } = await import('@tauri-apps/api/window')
  return getCurrentWindow()
}

// Downloads directory path, resolved once (mirrors useTauriDownload behavior).
let downloadDirPromise: Promise<string | null> | null = null
function getDownloadDir(): Promise<string | null> {
  if (!downloadDirPromise) {
    downloadDirPromise = (async () => {
      try {
        const { downloadDir } = await import('@tauri-apps/api/path')
        return await downloadDir()
      } catch (e) {
        console.warn('[tauriBridge] Failed to resolve downloads directory:', e)
        return null
      }
    })()
  }
  return downloadDirPromise
}

/**
 * Generate a unique filename by appending " (N)" if the file already exists
 * in the Downloads folder.
 */
async function getUniqueDownloadFilename(baseFilename: string): Promise<string> {
  const downloadDirectory = await getDownloadDir()
  if (!downloadDirectory) return baseFilename

  try {
    const { exists } = await import('@tauri-apps/plugin-fs')

    const fullPath = `${downloadDirectory}/${baseFilename}`
    if (!(await exists(fullPath))) {
      return baseFilename
    }

    const lastDot = baseFilename.lastIndexOf('.')
    const name = lastDot > 0 ? baseFilename.substring(0, lastDot) : baseFilename
    const ext = lastDot > 0 ? baseFilename.substring(lastDot) : ''

    let counter = 1
    while (counter < 1000) {
      const newFilename = `${name} (${counter})${ext}`
      if (!(await exists(`${downloadDirectory}/${newFilename}`))) {
        return newFilename
      }
      counter++
    }

    return `${name}_${Date.now()}${ext}`
  } catch (e) {
    console.error('[tauriBridge] Error checking file existence:', e)
    return baseFilename
  }
}

export const tauriBridge: DesktopBridge = {
  kind: 'tauri',

  // ---- app / backend -------------------------------------------------------
  async getBackendPort() {
    const { invoke } = await core()
    return invoke<number>('get_backend_port')
  },

  async getAppVersion() {
    const { getVersion } = await import('@tauri-apps/api/app')
    return getVersion()
  },

  async relaunch() {
    const { relaunch } = await import('@tauri-apps/plugin-process')
    await relaunch()
  },

  async log(level, message) {
    const { invoke } = await core()
    await invoke('log_from_webview', { level, message })
  },

  // ---- windows / profiles --------------------------------------------------
  async getWindowProfile() {
    const { invoke } = await core()
    return (await invoke<string | null>('get_window_profile')) || null
  },

  async reportWindowProfile(profileId) {
    const { invoke } = await core()
    await invoke('report_window_profile', { profileId })
  },

  // Multi-device is Electron-only; Tauri is kept runnable purely for the
  // migration and never grows this feature.
  async mdGetState() {
    return {
      activeDeviceId: 'local',
      connectionState: 'ready' as const,
      devices: [],
      localDeviceId: 'local',
    }
  },
  async mdRefreshDevices() {
    return []
  },
  async mdLocalStatus() {
    return { serving: false } as LocalDeviceStatus
  },
  async mdSetLocalServing() {
    return { serving: false } as LocalDeviceStatus
  },
  async mdRenameLocal() {
    return { serving: false } as LocalDeviceStatus
  },
  async mdForgetDevice() {},
  async mdSetActiveDevice() {
    return 'ready' as const
  },
  async mdUseLocalServer() {
    return 'ready' as const
  },
  async mdRetry() {
    return 'ready' as const
  },
  mdOnConnectionState() {
    return () => {}
  },
  // No device switching under Tauri, so the sidecar IS this install.
  async authLocal(method, path, body) {
    const port = await tauriBridge.getBackendPort()
    return fetchLocalAuth(`http://127.0.0.1:${port}`, method, path, body)
  },

  async openProfileWindow(profileId) {
    const { invoke } = await core()
    await invoke('open_profile_window', { profileId })
  },

  async closeDeletedProfileWindow() {
    const { invoke } = await core()
    return invoke<boolean>('close_deleted_profile_window')
  },

  async closeCurrentWindow() {
    const win = await currentWindow()
    await win.close()
  },

  async setWindowTitle(title) {
    const win = await currentWindow()
    await win.setTitle(title)
  },

  async setWindowSize(width, height) {
    const { getCurrentWindow, LogicalSize } = await import('@tauri-apps/api/window')
    await getCurrentWindow().setSize(new LogicalSize(width, height))
  },

  async focusCurrentWindow() {
    const win = await currentWindow()
    await win.show()
    await win.unminimize()
    await win.setFocus()
  },

  // ---- shell ---------------------------------------------------------------
  async openExternal(url) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  },

  async openAuthUrl(url) {
    const { invoke } = await core()
    await invoke('open_external_url', { url })
  },

  async openPath(path) {
    const { openPath } = await import('@tauri-apps/plugin-opener')
    await openPath(path)
  },

  async revealItemInDir(path) {
    const { revealItemInDir } = await import('@tauri-apps/plugin-opener')
    await revealItemInDir(path)
  },

  // ---- clipboard -----------------------------------------------------------
  async writeClipboardText(text) {
    const { writeText } = await import('@tauri-apps/plugin-clipboard-manager')
    await writeText(text)
  },

  // ---- dialogs -------------------------------------------------------------
  async pickDirectory(options?: DirectoryPickerOptions) {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      directory: true,
      multiple: false,
      title: options?.title,
      defaultPath: options?.defaultPath,
    })
    return typeof selected === 'string' ? selected : null
  },

  // ---- downloads -----------------------------------------------------------
  async saveToDownloads(filename, data) {
    const downloadDirectory = await getDownloadDir()
    if (!downloadDirectory) {
      console.error('[tauriBridge] Cannot save: no downloads directory')
      return false
    }
    try {
      const { writeFile, BaseDirectory } = await import('@tauri-apps/plugin-fs')
      const uniqueFilename = await getUniqueDownloadFilename(filename)
      await writeFile(uniqueFilename, data, { baseDir: BaseDirectory.Download })
      return true
    } catch (e) {
      console.error('[tauriBridge] Failed to save file:', e)
      return false
    }
  },

  // ---- print ---------------------------------------------------------------
  async print() {
    const { invoke } = await core()
    await invoke('print_webview')
  },

  // ---- drag-out ------------------------------------------------------------
  async startNativeDrag(items, previewImage) {
    const { invoke, Channel } = await core()
    const onEventChannel = new Channel()
    onEventChannel.onmessage = (event: unknown) => {
      console.log('[tauriBridge] Drag event:', event)
    }
    await invoke('plugin:drag|start_drag', {
      item: items,
      image: previewImage || items[0],
      onEvent: onEventChannel,
    })
  },

  async embedMetadata(req) {
    const { invoke } = await core()
    const path = await invoke<unknown>('embed_metadata', { req })
    return typeof path === 'string' && path.length > 0 ? path : null
  },

  async isShiftKeyDown() {
    const { invoke } = await core()
    return invoke<boolean>('shift_key_down')
  },

  // ---- voice ---------------------------------------------------------------
  async voiceModelStatus() {
    const { invoke } = await core()
    return invoke<boolean>('voice_model_status')
  },

  async voiceDownloadModel(onEvent) {
    const { invoke, Channel } = await core()
    const chan = new Channel<VoiceDownloadEvent>()
    chan.onmessage = onEvent
    await invoke('voice_download_model', { onEvent: chan })
  },

  async voiceStart(onEvent) {
    const { invoke, Channel } = await core()
    const chan = new Channel<VoiceTranscriptEvent>()
    chan.onmessage = onEvent
    await invoke('voice_start', { onEvent: chan })
  },

  async voiceStop() {
    const { invoke } = await core()
    return invoke<string>('voice_stop')
  },

  async voiceCancel() {
    const { invoke } = await core()
    await invoke('voice_cancel')
  },

  async voiceKeepalive() {
    const { invoke } = await core()
    await invoke('voice_keepalive')
  },

  // ---- updater -------------------------------------------------------------
  async checkForUpdate() {
    const updater = await import('@tauri-apps/plugin-updater')
    const update = await updater.check()
    return (update as unknown as DesktopUpdate | null) ?? null
  },

  // ---- tablet --------------------------------------------------------------
  async onTabletInput(callback) {
    const { listen } = await import('@tauri-apps/api/event')
    return listen('tablet-input', ({ payload }) => callback(payload))
  },
}
