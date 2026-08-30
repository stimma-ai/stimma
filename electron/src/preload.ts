/**
 * Sandboxed preload: exposes the DesktopBridge contract as
 * window.stimmaDesktop via contextBridge. Individually named, typed methods
 * only — no raw ipcRenderer, no generic command dispatcher.
 *
 * Method set must stay in lockstep with frontend/src/desktop/types.ts
 * (enforced by electron/tests/bridge-contract.test.ts).
 */

import { contextBridge, ipcRenderer, webUtils } from 'electron'

// ---- WKWebView localStorage import (Tauri→Electron migration) --------------
// Preload runs before any page script, so keys written here are visible to
// module-init reads (profileId, stimma_bundle_id). Only absent keys are
// written; the main process gates the dump behind a one-shot marker.
try {
  const legacyDump = ipcRenderer.sendSync('stimma:legacy-storage-dump') as
    | Record<string, string>
    | null
  if (legacyDump) {
    let written = 0
    for (const [key, value] of Object.entries(legacyDump)) {
      if (window.localStorage.getItem(key) === null) {
        window.localStorage.setItem(key, value)
        written++
      }
    }
    ipcRenderer.send('stimma:legacy-storage-imported', written)
  }
} catch (e) {
  // Never block app boot on the import; the marker stays unset so the next
  // launch retries.
  console.error('[legacy-storage] import failed in preload:', e)
}

function invoke<T>(channel: string, ...args: unknown[]): Promise<T> {
  return ipcRenderer.invoke(channel, ...args) as Promise<T>
}

// Streaming events (voice download/transcript) arrive on dedicated channels;
// each start call installs exactly one listener, removed when the stream ends.
function subscribeStream(
  channel: string,
  onEvent: (ev: unknown) => void,
): () => void {
  const listener = (_event: unknown, payload: unknown) => {
    onEvent(payload)
  }
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}

const stimmaDesktop = {
  kind: 'electron' as const,

  // ---- app / backend -------------------------------------------------------
  getBackendPort: () => invoke<number>('stimma:get-backend-port'),
  getAppVersion: () => invoke<string>('stimma:get-app-version'),
  relaunch: () => invoke<void>('stimma:relaunch'),
  log: (level: string, message: string) => invoke<void>('stimma:log', level, message),

  // ---- windows / profiles --------------------------------------------------
  getWindowProfile: () => invoke<string | null>('stimma:get-window-profile'),
  reportWindowProfile: (profileId: string) =>
    invoke<void>('stimma:report-window-profile', profileId),
  openProfileWindow: (profileId: string) =>
    invoke<void>('stimma:open-profile-window', profileId),
  closeDeletedProfileWindow: () => invoke<boolean>('stimma:close-deleted-profile-window'),
  closeCurrentWindow: () => invoke<void>('stimma:close-current-window'),
  setWindowTitle: (title: string) => invoke<void>('stimma:set-window-title', title),
  setWindowSize: (width: number, height: number) =>
    invoke<void>('stimma:set-window-size', width, height),
  focusCurrentWindow: () => invoke<void>('stimma:focus-current-window'),

  // ---- shell ---------------------------------------------------------------
  openExternal: (url: string) => invoke<void>('stimma:open-external', url),
  openAuthUrl: (url: string) => invoke<void>('stimma:open-auth-url', url),
  openPath: (path: string) => invoke<void>('stimma:open-path', path),
  revealItemInDir: (path: string) => invoke<void>('stimma:reveal-item', path),

  // ---- clipboard -----------------------------------------------------------
  writeClipboardText: (text: string) => invoke<void>('stimma:clipboard-write-text', text),

  // ---- dialogs -------------------------------------------------------------
  pickDirectory: (options?: { title?: string; defaultPath?: string }) =>
    invoke<string | null>('stimma:pick-directory', options ?? {}),

  // ---- downloads -----------------------------------------------------------
  saveToDownloads: (filename: string, data: Uint8Array) =>
    invoke<boolean>('stimma:save-to-downloads', filename, data),

  // ---- print ---------------------------------------------------------------
  print: () => invoke<void>('stimma:print'),

  // ---- drag-out ------------------------------------------------------------
  startNativeDrag: (items: string[], previewImage?: string) =>
    invoke<void>('stimma:start-native-drag', items, previewImage ?? null),
  embedMetadata: (req: unknown) => invoke<string | null>('stimma:embed-metadata', req),
  isShiftKeyDown: () => invoke<boolean>('stimma:is-shift-key-down'),

  // ---- voice ---------------------------------------------------------------
  voiceModelStatus: () => invoke<boolean>('stimma:voice-model-status'),
  voiceDownloadModel: async (onEvent: (ev: unknown) => void) => {
    const unsubscribe = subscribeStream('stimma:voice-download-event', onEvent)
    try {
      await invoke<void>('stimma:voice-download-model')
    } finally {
      unsubscribe()
    }
  },
  voiceStart: async (onEvent: (ev: unknown) => void) => {
    // Transcript events keep flowing until voiceStop/voiceCancel resolves;
    // the main process stops emitting after the session ends, and the next
    // voiceStart replaces the listener.
    replaceVoiceSessionListener(onEvent)
    await invoke<void>('stimma:voice-start')
  },
  voiceStop: () => invoke<string>('stimma:voice-stop'),
  voiceCancel: () => invoke<void>('stimma:voice-cancel'),
  voiceKeepalive: () => invoke<void>('stimma:voice-keepalive'),

  // ---- updater -------------------------------------------------------------
  checkForUpdate: async () => {
    const info = await invoke<{ version: string; body?: string; date?: string } | null>(
      'stimma:updater-check',
    )
    if (!info) return null
    return {
      version: info.version,
      body: info.body,
      date: info.date,
      download: () => invoke<void>('stimma:updater-download'),
      install: () => invoke<void>('stimma:updater-install'),
      downloadAndInstall: () => invoke<void>('stimma:updater-download-and-install'),
      close: () => invoke<void>('stimma:updater-close'),
    }
  },

  // ---- tablet --------------------------------------------------------------
  onTabletInput: async (callback: (payload: unknown) => void) => {
    // Chromium delivers pen pressure/tilt through PointerEvents natively, so
    // there is no separate native tablet stream in the Electron shell. Keep
    // the contract: resolve a no-op unsubscriber.
    void callback
    return () => {}
  },
}

let voiceSessionUnsubscribe: (() => void) | null = null
function replaceVoiceSessionListener(onEvent: (ev: unknown) => void): void {
  voiceSessionUnsubscribe?.()
  voiceSessionUnsubscribe = subscribeStream('stimma:voice-transcript-event', onEvent)
}

contextBridge.exposeInMainWorld('stimmaDesktop', stimmaDesktop)

// webUtils is imported so future file-drop paths can resolve File → path
// without widening the bridge; unused today.
void webUtils
