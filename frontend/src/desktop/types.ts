/**
 * Shell-neutral desktop bridge.
 *
 * Everything the frontend needs from the native desktop shell goes through
 * this interface. Implementations: tauriBridge (current shell), browserBridge
 * (plain web dev + tests), and later an Electron preload-backed bridge.
 * Application code must not import `@tauri-apps/*` or touch
 * `__TAURI_INTERNALS__` directly — only bridge implementations may.
 */

export type DesktopKind = 'tauri' | 'electron' | 'browser'

/** Progress events streamed while the voice model downloads. */
export type VoiceDownloadEvent =
  | { type: 'progress'; downloaded: number; total?: number | null }
  | { type: 'done' }
  | { type: 'error'; message: string }

/** Interim transcript events streamed while recording. */
export type VoiceTranscriptEvent =
  | { type: 'partial'; text: string }
  | { type: 'error'; message: string }

/**
 * A staged application update. Mirrors the Tauri updater resource shape so
 * the updater flow is shell-agnostic; the Electron implementation adapts
 * electron-updater to the same contract.
 */
export interface DesktopUpdate {
  version: string
  body?: string
  date?: string
  download: (onEvent?: (progress: unknown) => void) => Promise<void>
  install: () => Promise<void>
  downloadAndInstall: (onEvent?: (progress: unknown) => void) => Promise<void>
  close: () => Promise<void>
}

export interface DirectoryPickerOptions {
  title?: string
  defaultPath?: string
}

export type ConnectionState = 'connecting' | 'ready' | 'unreachable'

export interface DeviceRoute {
  kind: 'lan' | 'tailscale'
  host: string
  port: number
}

export interface DeviceRecord {
  deviceId: string
  name: string
  platform: string
  serving: boolean
  routes: DeviceRoute[]
  certFingerprint: string | null
  lastSeenAt?: string
}

export interface MultiDeviceState {
  activeDeviceId: string
  connectionState: ConnectionState
  devices: DeviceRecord[]
  localDeviceId: string
}

export interface DesktopBridge {
  readonly kind: DesktopKind

  // ---- app / backend -------------------------------------------------------
  /** Backend HTTP port from the native supervisor. Rejects outside desktop. */
  getBackendPort(): Promise<number>
  /** Packaged application version (not the frontend bundle version). */
  getAppVersion(): Promise<string>
  /** Relaunch the application (updater apply, dev tools). */
  relaunch(): Promise<void>
  /** Forward a webview console line into the native app log. Fire-and-forget. */
  log(level: string, message: string): Promise<void>

  // ---- multi-device --------------------------------------------------------
  /** Active device, connection state, and the cached device list. */
  mdGetState(): Promise<MultiDeviceState>
  /** Re-read the account device registry (via the local backend). */
  mdRefreshDevices(): Promise<DeviceRecord[]>
  /** Switch the window to a device; main reloads the window on success. */
  mdSetActiveDevice(deviceId: string): Promise<ConnectionState>
  /** Explicit fallback from the unreachable screen. Never automatic. */
  mdUseThisComputer(): Promise<ConnectionState>
  /** Retry the current device now. */
  mdRetry(): Promise<ConnectionState>
  /** Subscribe to connection transitions; returns an unsubscribe function. */
  mdOnConnectionState(onEvent: (state: ConnectionState) => void): () => void

  // ---- windows / profiles --------------------------------------------------
  /** Profile this window is pinned to, or null for the bootstrap window. */
  getWindowProfile(): Promise<string | null>
  /** Record which profile this window resolved to (restore + focus target). */
  reportWindowProfile(profileId: string): Promise<void>
  /** Focus the profile's window if open, otherwise open a new one. */
  openProfileWindow(profileId: string): Promise<void>
  /**
   * Close this window because its profile was deleted. Resolves false when it
   * is the last window — the caller switches profile in place instead.
   */
  closeDeletedProfileWindow(): Promise<boolean>
  /** Close the current window (browser-style close semantics apply natively). */
  closeCurrentWindow(): Promise<void>
  /** Set the current window's title. */
  setWindowTitle(title: string): Promise<void>
  /** Resize the current window (dev tooling). */
  setWindowSize(width: number, height: number): Promise<void>
  /** Show, unminimize, and focus the current window. */
  focusCurrentWindow(): Promise<void>

  // ---- shell ---------------------------------------------------------------
  /** Open an external URL in the default browser. */
  openExternal(url: string): Promise<void>
  /**
   * Open an auth URL in the default browser via the hardened native path
   * (validates http/https; avoids AppImage xdg-open environment leakage).
   */
  openAuthUrl(url: string): Promise<void>
  /** Open a filesystem path with the OS default handler. */
  openPath(path: string): Promise<void>
  /** Reveal a file in Finder/Explorer/file manager. */
  revealItemInDir(path: string): Promise<void>

  // ---- clipboard -----------------------------------------------------------
  writeClipboardText(text: string): Promise<void>

  // ---- dialogs -------------------------------------------------------------
  /** Native directory picker. Resolves null when cancelled or unsupported. */
  pickDirectory(options?: DirectoryPickerOptions): Promise<string | null>

  // ---- downloads -----------------------------------------------------------
  /**
   * Write bytes into the user's Downloads folder, uniquifying the filename if
   * it already exists. Resolves true on success.
   */
  saveToDownloads(filename: string, data: Uint8Array): Promise<boolean>

  // ---- print ---------------------------------------------------------------
  /** Native print dialog for the current webview. */
  print(): Promise<void>

  // ---- drag-out ------------------------------------------------------------
  /**
   * Begin a native OS file drag. Must be called synchronously within the
   * originating mouse gesture — never await anything first.
   */
  startNativeDrag(items: string[], previewImage?: string): Promise<void>
  /**
   * Splice prepared metadata into a media file copy (byte-level, no
   * re-encode). Resolves the path of the embedded snapshot, or null.
   */
  embedMetadata(req: unknown): Promise<string | null>
  /**
   * Current physical shift-key state, readable mid-drag (WKWebView does not
   * populate modifiers on DOM drag events). Non-macOS shells return false.
   */
  isShiftKeyDown(): Promise<boolean>

  // ---- voice ---------------------------------------------------------------
  /** Whether the dictation model is downloaded and ready. */
  voiceModelStatus(): Promise<boolean>
  voiceDownloadModel(onEvent: (ev: VoiceDownloadEvent) => void): Promise<void>
  voiceStart(onEvent: (ev: VoiceTranscriptEvent) => void): Promise<void>
  /** Stop recording and resolve the final cleaned transcript. */
  voiceStop(): Promise<string>
  voiceCancel(): Promise<void>
  voiceKeepalive(): Promise<void>

  // ---- updater -------------------------------------------------------------
  /** Check the update feed. Resolves null when up to date or unsupported. */
  checkForUpdate(): Promise<DesktopUpdate | null>

  // ---- tablet --------------------------------------------------------------
  /**
   * Subscribe to native stylus events (pressure/tilt/proximity). Resolves an
   * unsubscribe function. Shells without a native tablet stream resolve a
   * no-op unsubscriber and never call back.
   */
  onTabletInput(callback: (payload: unknown) => void): Promise<() => void>
}
