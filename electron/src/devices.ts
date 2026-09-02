/**
 * Active-device selection and remote session credentials.
 *
 * Main owns which device the window is on, because the unreachable state has
 * to enumerate devices while nothing is reachable — so the list cannot live
 * in the remote backend, and making a satellite boot a full local Python
 * backend just to list devices is exactly the "dumped into an empty local
 * install" failure the feature exists to prevent.
 *
 * The local Python backend stays the account authority: it holds the refresh
 * token in OS credential storage and talks to the registry. The one hand-off
 * is `/api/multi-device/connect-token`, used once per device to bootstrap.
 * After that we hold a session credential in Electron safeStorage and can
 * reach the remote device on later launches without local Python at all.
 */

import { safeStorage } from 'electron'
import fs from 'node:fs'
import https from 'node:https'
import path from 'node:path'
import type tls from 'node:tls'
import { log } from './log.ts'
import { fingerprintMatches, setProxyTarget, type ProxyTarget } from './proxy.ts'

export interface DeviceRoute {
  kind: 'lan' | 'tailscale'
  host: string
  port: number
}

export interface DeviceRecord {
  deviceId: string
  name: string
  platform: string
  /** In the roster at all — i.e. this computer was offered. */
  serving: boolean
  /** Up right now, per the account's push channel. */
  online?: boolean
  channel?: string | null
  sandbox?: string | null
  routes: DeviceRoute[]
  certFingerprint: string | null
  lastSeenAt?: string
}

export type ConnectionState = 'connecting' | 'ready' | 'unreachable'

/** "local" means this install's own backend. */
export const LOCAL_DEVICE = 'local'

interface PersistedState {
  activeDeviceId: string
  devices: DeviceRecord[]
  /** deviceId -> encrypted session, base64. Decrypted only in this process. */
  sessions: Record<string, string>
}

let statePath = ''
let state: PersistedState = { activeDeviceId: LOCAL_DEVICE, devices: [], sessions: {} }
let localBackendPort: number | null = null
let connectionState: ConnectionState = 'connecting'
let onStateChange: ((state: ConnectionState) => void) | null = null

export function initDevices(dataDir: string): void {
  statePath = path.join(dataDir, 'devices.json')
  try {
    const parsed = JSON.parse(fs.readFileSync(statePath, 'utf8'))
    if (parsed && typeof parsed === 'object') {
      state = {
        activeDeviceId: typeof parsed.activeDeviceId === 'string' ? parsed.activeDeviceId : LOCAL_DEVICE,
        devices: Array.isArray(parsed.devices) ? parsed.devices : [],
        sessions: parsed.sessions && typeof parsed.sessions === 'object' ? parsed.sessions : {},
      }
    }
  } catch {
    // First launch, or a corrupt file: default to the local server.
  }
}

function persist(): void {
  if (!statePath) return
  try {
    const tmp = statePath + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2))
    fs.renameSync(tmp, statePath)
  } catch (e) {
    log.warn('devices', `Failed to persist device state: ${e}`)
  }
}

export function setConnectionStateListener(fn: (state: ConnectionState) => void): void {
  onStateChange = fn
}

function setConnectionState(next: ConnectionState): void {
  if (connectionState === next) return
  connectionState = next
  log.info('devices', `Connection state: ${next}`)
  onStateChange?.(next)
}

export function getConnectionState(): ConnectionState {
  return connectionState
}

export function getActiveDeviceId(): string {
  return state.activeDeviceId
}

export function getKnownDevices(): DeviceRecord[] {
  return state.devices
}

/**
 * Called by backend.ts whenever the local Python port is known.
 *
 * Always (re)connects, not just for the local device: a satellite boots with
 * a REMOTE active device and must dial it here. Bootstrapping a session
 * needs the local backend for an account token, so this is the earliest
 * point at which a remote connect can succeed.
 */
export function setLocalBackendPort(port: number): void {
  localBackendPort = port
  void (async () => {
    if (state.activeDeviceId !== LOCAL_DEVICE) {
      // Routes and fingerprints may have changed since we last ran; the
      // cached list is only the fallback for when the registry is down.
      await refreshDevices()
    }
    await connect()
  })()
}

// --- session storage -------------------------------------------------------

function storeSession(deviceId: string, session: string): void {
  try {
    if (safeStorage.isEncryptionAvailable()) {
      state.sessions[deviceId] = safeStorage.encryptString(session).toString('base64')
    } else {
      // No OS keyring (a bare Linux session, say). Losing the cached session
      // costs one extra bootstrap, so degrade rather than fail.
      log.warn('devices', 'safeStorage unavailable; session not persisted')
      delete state.sessions[deviceId]
    }
  } catch (e) {
    log.warn('devices', `Failed to store session: ${e}`)
  }
  persist()
}

function loadSession(deviceId: string): string | null {
  const encrypted = state.sessions[deviceId]
  if (!encrypted) return null
  try {
    if (!safeStorage.isEncryptionAvailable()) return null
    return safeStorage.decryptString(Buffer.from(encrypted, 'base64'))
  } catch {
    return null
  }
}

export function clearSessions(): void {
  state.sessions = {}
  persist()
}

// --- local backend calls ---------------------------------------------------

async function localFetch(pathname: string, init?: RequestInit): Promise<any> {
  if (localBackendPort === null) throw new Error('local backend not ready')
  const response = await fetch(`http://127.0.0.1:${localBackendPort}${pathname}`, init)
  if (!response.ok) throw new Error(`${pathname} -> ${response.status}`)
  return response.json()
}

/**
 * Refresh the device list from the account registry, via local Python.
 *
 * Only an AUTHORITATIVE answer replaces the cache. The endpoint answers 200
 * with an empty list whenever it could not reach the registry, so keying on
 * HTTP success would let a cloud outage silently erase every known device —
 * and the cache is exactly what lets the chip render, and the unreachable
 * screen name the device it is waiting for, while nothing is reachable.
 */
export async function refreshDevices(): Promise<DeviceRecord[]> {
  try {
    const data = await localFetch('/api/multi-device/devices')
    if (data?.registryError) {
      // Signed in, but the registry did not answer. Say which it was: read as
      // "signed out" this looks like a feature nobody turned on, and the
      // stale cache below makes it look like it half works.
      log.warn('devices', `Registry unreachable (${data.registryError}); keeping cached list`)
      return state.devices
    }
    if (data?.signedIn !== true) {
      log.info('devices', 'Not signed in; keeping cached device list')
      return state.devices
    }
    state.devices = (data.devices ?? []).filter(
      (d: DeviceRecord) => d.deviceId !== data.selfDeviceId
    )
    persist()
  } catch (e) {
    log.warn('devices', `Device refresh failed, using cache: ${e}`)
  }
  return state.devices
}

/**
 * This physical computer's own multi-device state — never the active device's.
 *
 * Everything else in the window belongs to whichever device it is on, but
 * "is this computer offered, and what is it called" is about the machine in
 * front of you. Reading it through the proxy would answer for the machine you
 * are driving, which is how a satellite ends up showing the studio machine's
 * name under the heading "This computer" and toggling ITS serving switch.
 */
export async function localStatus(): Promise<unknown> {
  return localFetch('/api/multi-device/status')
}

export async function setLocalServing(enabled: boolean): Promise<unknown> {
  const status = await localFetch('/api/multi-device/serving', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  await refreshDevices()
  return status
}

export async function renameLocal(name: string): Promise<unknown> {
  const status = await localFetch('/api/multi-device/name', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  await refreshDevices()
  return status
}

/** Housekeeping removal from the account roster. Account-scoped, not local. */
export async function forgetDevice(deviceId: string): Promise<void> {
  await localFetch(`/api/multi-device/devices/${encodeURIComponent(deviceId)}`, {
    method: 'DELETE',
  })
  await refreshDevices()
}

// --- connecting ------------------------------------------------------------

/**
 * Request a pinned HTTPS endpoint on a serving device.
 *
 * Node's global fetch cannot be given a per-request TLS policy, and these
 * certificates are self-signed by design — trust comes from the fingerprint
 * the account registry published, not from a CA. So every call to a device
 * goes through here, and a fingerprint mismatch fails the request.
 */
function pinnedRequest(
  options: {
    host: string
    port: number
    path: string
    method?: string
    fingerprint: string
    session?: string
    body?: string
    timeoutMs?: number
  },
): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const headers: Record<string, string> = {}
    if (options.session) headers.authorization = `Bearer ${options.session}`
    if (options.body) {
      headers['content-type'] = 'application/json'
      headers['content-length'] = String(Buffer.byteLength(options.body))
    }

    const req = https.request(
      {
        host: options.host,
        port: options.port,
        path: options.path,
        method: options.method ?? 'GET',
        headers,
        rejectUnauthorized: false,
        checkServerIdentity: (_h: string, cert: tls.PeerCertificate) => {
          if (!cert?.raw || !fingerprintMatches(cert.raw, options.fingerprint)) {
            return new Error('certificate fingerprint mismatch')
          }
          return undefined
        },
      },
      (res) => {
        let body = ''
        res.setEncoding('utf8')
        res.on('data', (c) => (body += c))
        res.on('end', () => resolve({ status: res.statusCode ?? 0, body }))
      },
    )
    req.setTimeout(options.timeoutMs ?? 5000, () => req.destroy(new Error('timeout')))
    req.on('error', reject)
    if (options.body) req.write(options.body)
    req.end()
  })
}

/** Ping a candidate route, confirming it is a Stimma device and which one. */
async function probe(
  route: DeviceRoute,
  expectDeviceId: string,
  fingerprint: string,
): Promise<boolean> {
  try {
    const { status, body } = await pinnedRequest({
      host: route.host,
      port: route.port,
      path: '/multi-device/ping',
      fingerprint,
      timeoutMs: 2500,
    })
    if (status !== 200) return false
    // Confirms both that the pin held and that this really is the device the
    // registry named, not another Stimma install on the same address.
    return (JSON.parse(body) as { deviceId?: string }).deviceId === expectDeviceId
  } catch {
    return false
  }
}

async function bootstrapSession(device: DeviceRecord, route: DeviceRoute): Promise<string | null> {
  try {
    const { idToken, selfDeviceId } = await localFetch('/api/multi-device/connect-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deviceId: device.deviceId }),
    })

    const { status, body } = await pinnedRequest({
      host: route.host,
      port: route.port,
      path: '/multi-device/session',
      method: 'POST',
      fingerprint: device.certFingerprint!,
      body: JSON.stringify({ idToken, deviceId: selfDeviceId }),
      timeoutMs: 15000,
    })
    if (status !== 200) {
      log.warn('devices', `Bootstrap refused by ${device.name}: ${status}`)
      return null
    }
    return (JSON.parse(body) as { session?: string }).session ?? null
  } catch (e) {
    log.warn('devices', `Bootstrap failed for ${device.name}: ${e}`)
    return null
  }
}

/**
 * Point the proxy at the active device. LAN routes are tried before tailnet
 * ones because the registry orders them that way and a LAN hop is faster to
 * the same machine.
 */
export async function connect(): Promise<ConnectionState> {
  if (state.activeDeviceId === LOCAL_DEVICE) {
    if (localBackendPort === null) {
      setConnectionState('connecting')
      return connectionState
    }
    setProxyTarget({ host: '127.0.0.1', port: localBackendPort })
    setConnectionState('ready')
    return connectionState
  }

  setConnectionState('connecting')

  const device = state.devices.find((d) => d.deviceId === state.activeDeviceId)
  if (!device || !device.serving || !device.certFingerprint) {
    setProxyTarget(null)
    setConnectionState('unreachable')
    return connectionState
  }

  for (const route of device.routes) {
    if (!(await probe(route, device.deviceId, device.certFingerprint))) continue

    let session = loadSession(device.deviceId)
    let target: ProxyTarget = {
      host: route.host,
      port: route.port,
      tls: true,
      certFingerprint: device.certFingerprint,
      session: session ?? undefined,
    }

    // A cached session may have been revoked (serving turned off, sign-out).
    if (session && !(await sessionWorks(target))) {
      log.info('devices', `Cached session rejected by ${device.name}; re-bootstrapping`)
      session = null
    }

    if (!session) {
      session = await bootstrapSession(device, route)
      if (!session) continue
      storeSession(device.deviceId, session)
      target = { ...target, session }
    }

    setProxyTarget(target)
    setConnectionState('ready')
    log.info('devices', `Connected to ${device.name} via ${route.kind} ${route.host}:${route.port}`)
    return connectionState
  }

  setProxyTarget(null)
  setConnectionState('unreachable')
  return connectionState
}

async function sessionWorks(target: ProxyTarget): Promise<boolean> {
  try {
    const { status } = await pinnedRequest({
      host: target.host,
      port: target.port,
      path: '/api/profiles',
      fingerprint: target.certFingerprint!,
      session: target.session,
    })
    return status === 200
  } catch {
    return false
  }
}

/** Switch the window to a device. The caller reloads the window afterwards. */
export async function setActiveDevice(deviceId: string): Promise<ConnectionState> {
  state.activeDeviceId = deviceId
  persist()
  return connect()
}

/** Explicit "Use local server" from the unreachable screen. Never automatic. */
export async function useLocalServer(): Promise<ConnectionState> {
  return setActiveDevice(LOCAL_DEVICE)
}
