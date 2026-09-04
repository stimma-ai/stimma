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
import { log } from './log.ts'
import {
  getProxyTarget,
  pinnedConnection,
  setProxyFailureListener,
  setProxySessionInvalidListener,
  setProxyTarget,
  type ProxyTarget,
} from './proxy.ts'

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
  /** deviceId -> last route that completed a real authenticated connection. */
  preferredRoutes: Record<string, DeviceRoute>
}

let statePath = ''
let state: PersistedState = {
  activeDeviceId: LOCAL_DEVICE,
  devices: [],
  sessions: {},
  preferredRoutes: {},
}
let localBackendPort: number | null = null
let connectionState: ConnectionState = 'connecting'
/**
 * Whether the cached roster reflects the registry's last word. False until
 * local Python has answered once this run, and again after a route dies, so
 * a connect loop knows when re-reading the list could change the outcome.
 */
let devicesFresh = false

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))
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
        preferredRoutes:
          parsed.preferredRoutes && typeof parsed.preferredRoutes === 'object'
            ? parsed.preferredRoutes
            : {},
      }
    }
  } catch {
    // First launch, or a corrupt file: default to the local server.
  }
  setProxyFailureListener((failedTarget) => void recoverFromProxyFailure(failedTarget))
  setProxySessionInvalidListener((failedTarget) => void recoverFromSessionFailure(failedTarget))
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
 * Connects the local device right away: the renderer waits on that
 * backend's health itself. A satellite boots with a REMOTE active device
 * and dials it from here instead — but the port is announced before uvicorn
 * listens, while migrations still run, and bootstrapping a session needs
 * local Python for an account token. Dialling immediately therefore failed
 * every launch within a few hundred milliseconds and flashed "unreachable"
 * at a server that was fine. So wait until Python answers, and only then
 * start the patience window for the remote device.
 *
 * A remote session already established does not depend on local Python, so
 * a backend restart mid-session leaves it alone rather than re-dialling
 * (which would flash the connection screen over a healthy window).
 */
export function setLocalBackendPort(port: number): void {
  localBackendPort = port
  void (async () => {
    if (state.activeDeviceId === LOCAL_DEVICE) {
      await connect()
      return
    }
    if (connectionState === 'ready') return
    if (!(await waitForLocalBackend(port))) return
    // Routes and fingerprints may have changed since we last ran; the
    // cached list is only the fallback for when the registry is down.
    await refreshDevices()
    await connect({ patienceMs: CONNECT_PATIENCE_MS })
  })()
}

/**
 * Resolve true once local Python serves requests on `port`. No deadline, for
 * the same reason the renderer's own health wait has none: a one-time
 * migration has no honest upper bound. Resolves false if a newer port
 * supersedes this one first (the watchdog restarted the backend).
 */
async function waitForLocalBackend(port: number): Promise<boolean> {
  while (localBackendPort === port) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/`)
      if (response.ok) return true
    } catch {
      // Not listening yet.
    }
    await sleep(500)
  }
  return false
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

// --- account sign-in / sign-out ---------------------------------------------

/**
 * The only auth endpoints the renderer may reach through main. Anything else
 * still goes through the proxy to the active device.
 */
const LOCAL_AUTH_PATH = /^\/auth\/(status|start|logout|poll\/[A-Za-z0-9_-]+)$/

export interface LocalAuthResponse {
  ok: boolean
  status: number
  data: unknown
}

/**
 * Account sign-in and sign-out belong to the local island: they are about
 * THIS install, never the one the window is driving. Sent through the proxy
 * they would sign the REMOTE server's account in or out while this machine
 * stayed as it was — and the sign-in callback server would be bound on the
 * wrong computer.
 *
 * Status codes are passed through rather than thrown, because the renderer
 * reads them (a 403 in privacy lockdown, a 401 on an expired session).
 */
export async function localAuth(
  method: 'GET' | 'POST',
  pathname: string,
  body?: unknown,
): Promise<LocalAuthResponse> {
  if (!LOCAL_AUTH_PATH.test(pathname)) throw new Error(`Not a local auth path: ${pathname}`)
  if (localBackendPort === null) throw new Error('local backend not ready')

  const init: RequestInit = { method }
  if (body !== undefined && body !== null) {
    init.headers = { 'content-type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const response = await fetch(`http://127.0.0.1:${localBackendPort}/api${pathname}`, init)
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    // A body that is not JSON (or is empty) is reported as null.
  }

  if (method === 'POST' && pathname === '/auth/logout' && response.ok) onLocalLogout()

  return { ok: response.ok, status: response.status, data }
}

/**
 * Signed out = the feature does not exist. Every cached session was issued
 * to the account that just left, and a window driving a remote device is
 * now driving it with credentials the local backend can no longer renew.
 *
 * The active device is deliberately NOT switched back to local: the spec
 * forbids automatic switching, and the connection screen's explicit
 * "Use local server" is the way back. The persisted choice survives so a
 * sign-in can return to the same server.
 */
function onLocalLogout(): void {
  clearSessions()
  if (state.activeDeviceId === LOCAL_DEVICE) return
  // Supersede any connect still in flight so it cannot re-point the proxy at
  // the remote device after we have taken it away.
  connectGen++
  setProxyTarget(null)
  setConnectionState('unreachable')
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
      devicesFresh = false
      return state.devices
    }
    if (data?.signedIn !== true) {
      log.info('devices', 'Not signed in; keeping cached device list')
      // Authoritative in its own way: asking again changes nothing until a
      // sign-in, and that path clears the cache itself.
      devicesFresh = true
      return state.devices
    }
    state.devices = (data.devices ?? []).filter(
      (d: DeviceRecord) => d.deviceId !== data.selfDeviceId
    )
    devicesFresh = true
    persist()
  } catch (e) {
    log.warn('devices', `Device refresh failed, using cache: ${e}`)
    devicesFresh = false
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
  // The registry has accepted the removal, so the cache must not carry the
  // row a moment longer: the re-read below keeps the cache untouched when the
  // registry does not answer, and that would resurrect what was just removed.
  state.devices = state.devices.filter((d) => d.deviceId !== deviceId)
  persist()
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
        // No agent: with one set, Node ignores a per-request createConnection.
        // The pin has to sit in the socket factory (see proxy.ts) because
        // checkServerIdentity never runs for a self-signed peer.
        createConnection: pinnedConnection(options.fingerprint, options.timeoutMs ?? 5000),
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

function sameRoute(a: DeviceRoute | undefined, b: DeviceRoute): boolean {
  return !!a && a.host === b.host && a.port === b.port && a.kind === b.kind
}

/**
 * Probe all candidates within one bounded window instead of serially paying a
 * timeout for every stale interface. LAN gets a short head start over the
 * tailnet, while the last route known to work starts immediately regardless
 * of kind. Successful candidates are returned in observed-speed order.
 */
async function* reachableRoutes(device: DeviceRecord): AsyncGenerator<DeviceRoute> {
  const preferred = state.preferredRoutes[device.deviceId]
  const ready: DeviceRoute[] = []
  let remaining = device.routes.length
  let wake: (() => void) | null = null

  for (const route of device.routes) {
    const delay = route.kind === 'tailscale' && !sameRoute(preferred, route) ? 250 : 0
    void (async () => {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay))
      if (await probe(route, device.deviceId, device.certFingerprint!)) ready.push(route)
      remaining--
      wake?.()
      wake = null
    })()
  }

  while (remaining > 0 || ready.length > 0) {
    while (ready.length > 0) yield ready.shift()!
    if (remaining > 0) await new Promise<void>((resolve) => (wake = resolve))
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
 * How long an AUTOMATIC connect (launch, a route dying mid-session) keeps
 * sweeping in the connecting state before it admits the device is
 * unreachable. Networks come up after the app does, a woken machine takes a
 * moment to answer, and a laptop mid-switch between Wi-Fi networks fails
 * every probe instantly; none of those deserve a red screen on the first
 * miss. Explicit user actions (Retry, picking a device) get one sweep, so
 * the answer to a click is immediate.
 */
const CONNECT_PATIENCE_MS = 20_000
const SWEEP_PAUSE_MS = 1_000

/**
 * Point the proxy at the active device. Candidate probes are concurrent with
 * a small LAN head start, avoiding N serial timeouts before tailnet fallback.
 * With `patienceMs`, failed sweeps repeat — on a cached roster first, then a
 * re-read one if the last read was not authoritative — until the window
 * closes; the state stays `connecting` throughout.
 *
 * Calls overlap: a device switch while a probe is mid-flight, a retry from
 * the unreachable screen, the local backend restarting. Only the newest call
 * may touch the proxy or the connection state — otherwise the older one,
 * finishing later, would point the window at a device the user has already
 * left. A superseded call reports the state the winner established.
 */
let connectGen = 0

export async function connect(options: { patienceMs?: number } = {}): Promise<ConnectionState> {
  const gen = ++connectGen
  const deviceId = state.activeDeviceId
  const superseded = () => gen !== connectGen || state.activeDeviceId !== deviceId

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
  const deadline = Date.now() + (options.patienceMs ?? 0)

  for (let sweep = 0; ; sweep++) {
    // The first sweep runs on the cached roster: fast and cloud-independent.
    // Later ones re-read it when the last read was not the registry's word.
    if (sweep > 0 && !devicesFresh) await refreshDevices()
    if (superseded()) return connectionState

    const device = state.devices.find((d) => d.deviceId === deviceId)
    if (!device?.serving || !device.certFingerprint) {
      // The registry says this device is not offered: no amount of waiting
      // changes that. A stale cache saying so might, so keep the window open.
      if (devicesFresh) break
    } else if (await sweepRoutes(device, superseded)) {
      return connectionState
    }

    if (superseded()) return connectionState
    if (Date.now() >= deadline) break
    await sleep(SWEEP_PAUSE_MS)
  }

  if (superseded()) return connectionState
  setProxyTarget(null)
  setConnectionState('unreachable')
  return connectionState
}

/** One pass over a device's routes. True once the proxy points at it. */
async function sweepRoutes(device: DeviceRecord, superseded: () => boolean): Promise<boolean> {
  for await (const route of reachableRoutes(device)) {
    if (superseded()) return false

    let session = loadSession(device.deviceId)
    let target: ProxyTarget = {
      host: route.host,
      port: route.port,
      tls: true,
      certFingerprint: device.certFingerprint!,
      session: session ?? undefined,
    }

    // A cached session may have been revoked (serving turned off, sign-out).
    const sessionState = session ? await sessionWorks(target) : null
    if (session && sessionState === 'invalid') {
      log.info('devices', `Cached session rejected by ${device.name}; re-bootstrapping`)
      session = null
    }
    if (session && sessionState === 'unreachable') continue
    if (superseded()) return false

    if (!session) {
      session = await bootstrapSession(device, route)
      if (!session) continue
      // The session is valid for that device regardless of who wins, so
      // caching it is safe; pointing the proxy at it is not.
      storeSession(device.deviceId, session)
      target = { ...target, session }
      if (superseded()) return false
    }

    setProxyTarget(target)
    state.preferredRoutes[device.deviceId] = route
    persist()
    setConnectionState('ready')
    log.info('devices', `Connected to ${device.name} via ${route.kind} ${route.host}:${route.port}`)
    return true
  }
  return false
}

async function sessionWorks(target: ProxyTarget): Promise<'valid' | 'invalid' | 'unreachable'> {
  try {
    const { status } = await pinnedRequest({
      host: target.host,
      port: target.port,
      path: '/api/profiles',
      fingerprint: target.certFingerprint!,
      session: target.session,
    })
    // The serving gate returns 401 before the app for a missing/revoked
    // session. Other application statuses still prove that the credential
    // was accepted; do not turn a transient backend 500 into an auth event.
    return status === 401 || status === 403 ? 'invalid' : 'valid'
  } catch {
    return 'unreachable'
  }
}

let recoveryInFlight = false
let sessionRecoveryInFlight = false

/** Replace a revoked credential without declaring a healthy route dead. */
async function recoverFromSessionFailure(failedTarget: ProxyTarget): Promise<void> {
  if (sessionRecoveryInFlight || state.activeDeviceId === LOCAL_DEVICE) return
  if (getProxyTarget() !== failedTarget) return
  const device = state.devices.find((d) => d.deviceId === state.activeDeviceId)
  if (!device?.certFingerprint) return

  sessionRecoveryInFlight = true
  try {
    log.info('devices', `Session rejected by ${device.name}; re-bootstrapping`)
    const route: DeviceRoute = { host: failedTarget.host, port: failedTarget.port, kind: 'lan' }
    const session = await bootstrapSession(device, route)
    if (getProxyTarget() !== failedTarget) return
    if (session) {
      storeSession(device.deviceId, session)
      setProxyTarget({ ...failedTarget, session })
      return
    }

    setProxyTarget(null)
    devicesFresh = false
    await connect({ patienceMs: CONNECT_PATIENCE_MS })
  } finally {
    sessionRecoveryInFlight = false
  }
}

/**
 * A route that was healthy can disappear when a laptop changes networks.
 * Fail over using cached candidates first (fast and cloud-independent); if
 * none of them work the patient connect re-reads discovery and keeps trying
 * until its window closes.
 */
async function recoverFromProxyFailure(failedTarget: ProxyTarget): Promise<void> {
  if (recoveryInFlight || state.activeDeviceId === LOCAL_DEVICE) return
  if (getProxyTarget() !== failedTarget) return
  recoveryInFlight = true
  try {
    // Ask the route itself before believing the proxy. A cluster of failed
    // requests can be a pool artefact or one bad moment on a healthy link,
    // and announcing "connecting" for a route that still answers costs the
    // renderer its whole screen: the app unmounts behind the connection
    // screen and remounts a moment later, losing where the person was.
    if (await routeStillAnswers(failedTarget)) {
      log.info('devices', 'Active remote route still answers; keeping it')
      return
    }
    log.warn('devices', 'Active remote route failed; selecting another route')
    setProxyTarget(null)
    devicesFresh = false
    await connect({ patienceMs: CONNECT_PATIENCE_MS })
  } finally {
    recoveryInFlight = false
  }
}

/** The active route, probed fresh — not a pooled socket, not the session. */
async function routeStillAnswers(target: ProxyTarget): Promise<boolean> {
  const device = state.devices.find((d) => d.deviceId === state.activeDeviceId)
  if (!device || !target.certFingerprint) return false
  const route: DeviceRoute = { host: target.host, port: target.port, kind: 'lan' }
  // One fresh miss during a server/pool hiccup is not enough evidence to
  // unmount every renderer. Give the same pinned route a short grace period;
  // hard connect failures still finish each probe immediately.
  for (let attempt = 0; attempt < 3; attempt++) {
    if (await probe(route, device.deviceId, target.certFingerprint)) return true
    if (attempt < 2) await sleep(250)
  }
  return false
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
