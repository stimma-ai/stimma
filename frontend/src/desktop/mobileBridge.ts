/** Native phone shell. Account credentials stay behind the native bridge. */
import { browserBridge } from './browserBridge.ts'
import { checkMobileDownloadSize } from '../utils/mobileDownload.ts'
import { addToast } from '../composables/useToasts.ts'
import { mobileNative as native, mobilePlatform } from './mobileNative.ts'
import type { ConnectionState, DesktopBridge, DeviceRecord, LocalAuthResponse, MultiDeviceState, VoiceTranscriptEvent } from './types'

/** Native commands newer phone shells add; older shells and iOS list none of them. */
export type MobileFeature = 'print' | 'saveFile' | 'shareBase64' | 'voice'

export function hasMobileFeature(feature: MobileFeature): boolean {
  if (typeof window === 'undefined') return false
  const features: unknown = (window as Window & { stimmaNativeFeatures?: unknown }).stimmaNativeFeatures
  return Array.isArray(features) && features.includes(feature)
}

/** This phone saves exports into its own Photos and Downloads, rather than only sharing them. */
export function phoneSavesFiles(): boolean {
  return isMobileShell() && hasMobileFeature('saveFile')
}

/** Base64 without building one giant argument list. */
export function bytesToBase64(data: Uint8Array): string {
  const native = (data as Uint8Array & { toBase64?: () => string }).toBase64
  if (typeof native === 'function') return native.call(data)
  let binary = ''
  for (let start = 0; start < data.length; start += 0x8000) {
    binary += String.fromCharCode.apply(null, data.subarray(start, start + 0x8000) as unknown as number[])
  }
  return btoa(binary)
}

/** Hand a file to the phone's share sheet. Resolves false when the person cancels. */
export async function shareOnPhone(filename: string, data: Uint8Array): Promise<boolean> {
  checkMobileDownloadSize(data.byteLength, mobileBridge.kind)
  if (hasMobileFeature('shareBase64')) return await native<boolean>('share', { filename, base64: bytesToBase64(data) })
  return await native<boolean>('share', { filename, bytes: Array.from(data) })
}

const SAVED_MESSAGE: Record<string, string> = {
  photos: 'Saved to Photos',
  downloads: 'Saved to Downloads',
}

type VoiceStart = { started: boolean; session?: number; reason?: string; message?: string }
let voiceListener: ((event: Event) => void) | null = null
function stopVoiceEvents() {
  if (voiceListener) window.removeEventListener('stimma:voice', voiceListener)
  voiceListener = null
}

export function isMobileShell(): boolean {
  return mobilePlatform() !== undefined
}

/** Release the shell's loading cover only after Vue has rendered the app. */
export async function revealMobileInterface(): Promise<void> {
  if (!isMobileShell()) return
  await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
  // Older shells do not need the readiness notification.
  await native('interfaceReady').catch(() => {})
}

export function disconnectMobileServer(): Promise<void> {
  return native('disconnect')
}

/** The shell's own connection screen: server list, sign-in, dev server. */
export function showMobileConnections(): Promise<void> {
  return native('showConnections')
}

export async function setMobileSlideshowActive(active: boolean): Promise<void> {
  if (!isMobileShell()) return
  // Older native shells can still use this UI package.
  await native('setSlideshowActive', { active }).catch(() => {})
}

export async function setMobileKeepAwake(active: boolean): Promise<void> {
  if (!isMobileShell()) return
  await native('setKeepAwake', { active }).catch(() => {})
}

const wakeRequests = new Set<symbol>()
/** One owner's vote to keep the phone's screen on; the screen stays on while any owner votes yes. */
export function createMobileKeepAwakeLease(): (active: boolean) => Promise<void> {
  const owner = Symbol('keep-awake')
  return active => {
    if (active) wakeRequests.add(owner)
    else wakeRequests.delete(owner)
    return setMobileKeepAwake(wakeRequests.size > 0)
  }
}

export const mobileBridge: DesktopBridge = {
  ...browserBridge,
  get kind() { return mobilePlatform() ?? 'ios' },
  async getBackendPort() {
    const port = Number(window.location.port || (window.location.protocol === 'https:' ? 443 : 80))
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error('The mobile connection is unavailable')
    }
    return port
  },
  async relaunch() { await native('reload') },
  mdGetState() { return native<MultiDeviceState>('getState') },
  mdRefreshDevices() { return native<DeviceRecord[]>('refreshDevices') },
  async mdLocalStatus() { return { serving: false, platform: mobilePlatform() } },
  async mdSetLocalServing(enabled) {
    if (enabled) throw new Error('This phone connects to a computer and cannot serve a library')
    return { serving: false, platform: mobilePlatform() }
  },
  async mdRenameLocal() { throw new Error('This phone does not offer a server') },
  async mdForgetDevice() { throw new Error('Manage your computers in Stimma on desktop') },
  mdSetActiveDevice(deviceId) { return native<ConnectionState>('selectServer', { deviceId }) },
  async mdUseLocalServer() {
    await native('showConnections')
    return 'unreachable'
  },
  async mdRetry() {
    await native('reload')
    return (await native<MultiDeviceState>('getState')).connectionState
  },
  mdOnConnectionState(onEvent) {
    const listener = (event: Event) => {
      const state: unknown = (event as CustomEvent).detail
      if (state === 'ready' || state === 'connecting' || state === 'unreachable') onEvent(state)
    }
    window.addEventListener('stimma:connection-state', listener)
    return () => window.removeEventListener('stimma:connection-state', listener)
  },
  async authLocal(method, path) {
    if (method === 'GET' && path === '/auth/status') return native<LocalAuthResponse>('authStatus')
    if (method === 'POST' && path === '/auth/logout') {
      await native('logout')
      return { ok: true, status: 200, data: null }
    }
    if (method === 'POST' && path === '/auth/start') await native('showConnections')
    // Never forward account mutations to the computer serving this webview.
    return { ok: false, status: 501, data: { detail: 'Use the mobile app connection screen to sign in' } }
  },
  async closeCurrentWindow() { await native('showConnections') },
  async focusCurrentWindow() {},
  async openExternal(url) {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') throw new Error('Only web links can be opened')
    await native('openExternal', { url: parsed.href })
  },
  async openAuthUrl() { await native('showConnections') },
  async print() {
    if (!hasMobileFeature('print')) { window.print(); return }
    await native('print', { title: document.title })
  },
  async saveToDownloads(filename, data) {
    if (!hasMobileFeature('saveFile')) return await shareOnPhone(filename, data)
    checkMobileDownloadSize(data.byteLength, mobileBridge.kind)
    const saved = await native<{ location: string } | false>('saveFile', { filename, base64: bytesToBase64(data) })
    if (!saved) return false
    addToast(SAVED_MESSAGE[saved.location] ?? 'Saved', 'success')
    return true
  },
  // Dictation uses the phone's own speech recognizer: nothing to download.
  async voiceModelStatus() {
    if (!hasMobileFeature('voice')) return false
    try { return (await native<{ available: boolean }>('voiceStatus')).available === true } catch { return false }
  },
  async voiceDownloadModel() {
    throw new Error('Voice input isn\'t available on this phone')
  },
  async voiceStart(onEvent: (event: VoiceTranscriptEvent) => void) {
    if (!hasMobileFeature('voice')) throw new Error('Voice input isn\'t available on this phone')
    stopVoiceEvents()
    let session: number | undefined
    // Events can arrive before voiceStart answers with its session number.
    const early: Array<{ session?: number; event: VoiceTranscriptEvent }> = []
    const deliver = (event: VoiceTranscriptEvent) => {
      onEvent(event)
      if (event.type === 'error') stopVoiceEvents()
    }
    const listener = (event: Event) => {
      const detail = (event as CustomEvent).detail as { session?: number; type?: string; text?: string; message?: string } | undefined
      if (!detail) return
      const parsed: VoiceTranscriptEvent | null = detail.type === 'partial' ? { type: 'partial', text: String(detail.text ?? '') }
        : detail.type === 'error' ? { type: 'error', message: String(detail.message ?? 'Voice input stopped. Try again.') } : null
      if (!parsed) return
      if (session === undefined) early.push({ session: detail.session, event: parsed })
      else if (detail.session === session) deliver(parsed)
    }
    voiceListener = listener
    window.addEventListener('stimma:voice', listener)
    const result = await native<VoiceStart>('voiceStart')
    if (!result?.started) {
      stopVoiceEvents()
      if (result?.reason === 'cancelled') return
      throw new Error(result?.message || 'Voice input isn\'t available on this phone')
    }
    session = result.session
    for (const pending of early) if (voiceListener === listener && pending.session === session) deliver(pending.event)
  },
  async voiceStop() {
    if (!hasMobileFeature('voice')) return ''
    try { return String(await native<string>('voiceStop') ?? '') } finally { stopVoiceEvents() }
  },
  async voiceCancel() {
    stopVoiceEvents()
    if (hasMobileFeature('voice')) await native('voiceCancel').catch(() => {})
  },
  // Native dictation stops itself when the app leaves the screen.
  async voiceKeepalive() {},
}
