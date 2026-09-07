/** iOS WKWebView shell. Account credentials stay behind the native bridge. */
import { browserBridge } from './browserBridge.ts'
import { checkMobileDownloadSize } from '../utils/mobileDownload.ts'
import type { ConnectionState, DesktopBridge, DeviceRecord, LocalAuthResponse, MultiDeviceState } from './types'

type NativeHandler = {
  postMessage(message: { method: string; args: Record<string, unknown> }): Promise<unknown>
}

function handler(): NativeHandler | undefined {
  if (typeof window === 'undefined') return undefined
  return (window as unknown as { webkit?: { messageHandlers?: { stimma?: NativeHandler } } })
    .webkit?.messageHandlers?.stimma
}

export function isMobileShell(): boolean {
  return typeof handler()?.postMessage === 'function'
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

async function native<T>(method: string, args: Record<string, unknown> = {}): Promise<T> {
  const bridge = handler()
  if (!bridge) throw new Error('The mobile shell is unavailable')
  return await bridge.postMessage({ method, args }) as T
}

export async function setMobileSlideshowActive(active: boolean): Promise<void> {
  if (!isMobileShell() || mobileBridge.kind !== 'ios') return
  // Older native shells can still use this UI package.
  await native('setSlideshowActive', { active }).catch(() => {})
}

export async function setMobileKeepAwake(active: boolean): Promise<void> {
  if (!isMobileShell() || mobileBridge.kind !== 'ios') return
  await native('setKeepAwake', { active }).catch(() => {})
}

const wakeRequests = new Set<symbol>()
export function createMobileKeepAwakeLease(): (active: boolean) => Promise<void> {
  const owner = Symbol('slideshow')
  return active => {
    if (active) wakeRequests.add(owner)
    else wakeRequests.delete(owner)
    return setMobileKeepAwake(wakeRequests.size > 0)
  }
}

export const mobileBridge: DesktopBridge = {
  ...browserBridge,
  kind: 'ios',
  async getBackendPort() {
    const port = Number(window.location.port)
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error('The mobile connection is unavailable')
    }
    return port
  },
  async relaunch() { await native('reload') },
  mdGetState() { return native<MultiDeviceState>('getState') },
  mdRefreshDevices() { return native<DeviceRecord[]>('refreshDevices') },
  async mdLocalStatus() { return { serving: false, platform: 'ios' } },
  async mdSetLocalServing(enabled) {
    if (enabled) throw new Error('This phone connects to a computer and cannot serve a library')
    return { serving: false, platform: 'ios' }
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
  async saveToDownloads(filename, data) {
    checkMobileDownloadSize(data.byteLength, 'ios')
    return await native<boolean>('share', { filename, bytes: Array.from(data) })
  },
}
