/**
 * Browser/test implementation of the desktop bridge.
 *
 * Used in plain web dev, acceptance tests, and any environment without a
 * native shell. Web-capable operations get real browser fallbacks; native-only
 * operations are inert (resolve to a harmless default) so feature code can
 * call the bridge unconditionally where it already had no Tauri gate.
 */

import type { DesktopBridge, LocalAuthResponse, LocalDeviceStatus } from './types'

/**
 * Shared by the browser and Tauri bridges: one backend, so "this install"
 * and "the active device" are the same server. Mirrors the shape Electron
 * main returns so useAuth reads one contract.
 */
export async function fetchLocalAuth(
  origin: string,
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<LocalAuthResponse> {
  if (!path.startsWith('/auth/')) throw new Error(`Not a local auth path: ${path}`)
  const init: RequestInit = { method }
  if (body !== undefined && body !== null) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const response = await fetch(`${origin}/api${path}`, init)
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    // Empty or non-JSON body.
  }
  return { ok: response.ok, status: response.status, data }
}

export const browserBridge: DesktopBridge = {
  kind: 'browser',

  // ---- app / backend -------------------------------------------------------
  async getBackendPort() {
    throw new Error('No native backend supervisor outside the desktop app')
  },

  async getAppVersion() {
    throw new Error('App version is only available in the desktop app')
  },

  async relaunch() {
    throw new Error('Relaunch is only available in the desktop app')
  },

  async log() {
    // Console output already lands in the browser console.
  },

  // ---- windows / profiles --------------------------------------------------
  async getWindowProfile() {
    return null
  },

  async reportWindowProfile() {},

  // Outside a desktop shell there is exactly one backend and no device
  // switching, so the feature reports itself as absent rather than broken.
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
  // Plain web dev: relative /api, exactly where the API base points.
  authLocal(method, path, body) {
    return fetchLocalAuth('', method, path, body)
  },

  async openProfileWindow() {
    throw new Error('Profile windows are only available in the desktop app')
  },

  async closeDeletedProfileWindow() {
    return false
  },

  async closeCurrentWindow() {
    window.close()
  },

  async setWindowTitle(title) {
    document.title = title
  },

  async setWindowSize() {},

  async focusCurrentWindow() {
    window.focus()
  },

  // ---- shell ---------------------------------------------------------------
  async openExternal(url) {
    window.open(url, '_blank', 'noopener,noreferrer')
  },

  async openAuthUrl(url) {
    window.open(url, '_blank', 'noopener,noreferrer')
  },

  async openPath() {
    throw new Error('Opening filesystem paths is only available in the desktop app')
  },

  async revealItemInDir() {
    throw new Error('Revealing files is only available in the desktop app')
  },

  // ---- clipboard -----------------------------------------------------------
  async writeClipboardText(text) {
    await navigator.clipboard.writeText(text)
  },

  // ---- dialogs -------------------------------------------------------------
  async pickDirectory() {
    return null
  },

  // ---- downloads -----------------------------------------------------------
  async saveToDownloads(filename, data) {
    const blob = new Blob([data as unknown as BlobPart])
    const blobUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(blobUrl)
    return true
  },

  // ---- print ---------------------------------------------------------------
  async print() {
    window.print()
  },

  // ---- drag-out ------------------------------------------------------------
  async startNativeDrag() {
    throw new Error('Native drag-out is only available in the desktop app')
  },

  async embedMetadata() {
    return null
  },

  async isShiftKeyDown() {
    return false
  },

  // ---- voice ---------------------------------------------------------------
  async voiceModelStatus() {
    return false
  },

  async voiceDownloadModel() {
    throw new Error('Voice input requires the desktop app')
  },

  async voiceStart() {
    throw new Error('Voice input requires the desktop app')
  },

  async voiceStop() {
    return ''
  },

  async voiceCancel() {},

  async voiceKeepalive() {},

  // ---- updater -------------------------------------------------------------
  async checkForUpdate() {
    return null
  },

  // ---- tablet --------------------------------------------------------------
  async onTabletInput() {
    return () => {}
  },
}
