/**
 * Localhost proxy — the single origin the renderer ever talks to.
 *
 * The renderer is pointed at http://127.0.0.1:<proxy port> and never learns
 * whether it is driving the local Python backend or a remote device: main
 * owns that choice and re-points the target underneath it. Three things fall
 * out of that, and they are the reason this exists:
 *
 *   1. Media URLs never change. /api/db/{db_guid}/... is loaded by <img> and
 *      <video>, which cannot set headers, so remote auth has to be injected
 *      somewhere the renderer isn't. Doing it here keeps the thumbnail HTTP
 *      cache intact — a signed query token would bust it on every rotation.
 *   2. Switching device is not an origin change, so the renderer's API config
 *      singletons and the backend's CORS allowlist both stay untouched.
 *   3. The port is stable across launches. The Python backend binds an
 *      ephemeral port, so today every launch produces a new origin and starts
 *      with a cold Chromium disk cache; a stable proxy port fixes that for
 *      local use, independent of multi-device.
 *
 * Binds 127.0.0.1 only. This is an auth boundary once remote targets carry
 * credentials: anything that can reach this port can reach the active device.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import https from 'node:https'
import net from 'node:net'
import path from 'node:path'
import type stream from 'node:stream'
import tls from 'node:tls'
import { log } from './log.ts'

/** Where the proxy currently forwards. Null = nothing to talk to yet. */
export interface ProxyTarget {
  host: string
  port: number
  /** Remote devices are HTTPS; the local backend is plain loopback HTTP. */
  tls?: boolean
  /**
   * SHA-256 of the peer's certificate DER, from the account device registry.
   * Because the registry is per-account and authenticated, matching against
   * it is real pinning rather than trust-on-first-use — a LAN attacker
   * cannot substitute a certificate we would accept.
   */
  certFingerprint?: string
  /** Session credential injected on every request, including <img> loads. */
  session?: string
}

// Hop-by-hop headers are per-connection and must not be forwarded (RFC 9110
// 7.6.1). 'connection' itself also names additional per-connection headers,
// which we drop as well.
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

// Our own pool rather than http.globalAgent: a thumbnail grid opens many
// requests in a burst and should not pay TCP setup on each, and owning the
// agent means stopProxy() can actually tear the connections down.
const agent = new http.Agent({ keepAlive: true, maxSockets: 64 })

/**
 * Verify a peer certificate against a pinned SHA-256 of its DER.
 * Exported for tests: this is the one check standing between a remote
 * session and a man-in-the-middle.
 */
export function fingerprintMatches(der: Buffer, expected: string): boolean {
  const actual = crypto.createHash('sha256').update(der).digest('hex')
  // Constant-time: the fingerprint is public, but the habit is cheap and the
  // comparison is not on a hot path.
  const a = Buffer.from(actual)
  const b = Buffer.from(expected.toLowerCase())
  return a.length === b.length && crypto.timingSafeEqual(a, b)
}

type ConnectionCallback = (err: Error | null, socket: stream.Duplex) => void

/**
 * A socket factory that trusts exactly one certificate.
 *
 * CA verification is deliberately off: the certificate is self-signed by the
 * serving device, so there is no chain to check. Trust comes entirely from
 * the pinned fingerprint, which is strictly stronger here than the public CA
 * system would be for a LAN address.
 *
 * The check lives in `createConnection`, not `checkServerIdentity`: Node only
 * consults the latter once chain verification has PASSED, and with
 * `rejectUnauthorized: false` a self-signed peer never gets that far — the
 * callback is skipped and the socket is accepted. So the pin is enforced on
 * `secureConnect`, and the socket is handed to the HTTP layer only after the
 * fingerprint matches. Nothing is written to it before then.
 *
 * Returned in the shape http.Agent#createConnection / request.createConnection
 * expect, so one implementation covers the proxy pool, upgrades, and the
 * one-off device calls in devices.ts.
 */
export function pinnedConnection(expectedFingerprint: string) {
  return function createConnection(
    options: http.ClientRequestArgs,
    callback?: ConnectionCallback,
  ): undefined {
    const tlsOptions = options as tls.ConnectionOptions
    // RFC 6066 forbids an IP literal as SNI; Node warns and ignores it, and
    // LAN/tailnet routes are mostly IPs, so only send a real name.
    const servername =
      typeof tlsOptions.servername === 'string' && !net.isIP(tlsOptions.servername)
        ? tlsOptions.servername
        : undefined
    const socket = tls.connect({ ...tlsOptions, servername, rejectUnauthorized: false })

    let settled = false
    const fail = (err: Error) => {
      if (settled) return
      settled = true
      socket.destroy()
      callback?.(err, socket)
    }
    socket.once('error', fail)
    socket.once('secureConnect', () => {
      if (settled) return
      if (!expectedFingerprint) {
        fail(new Error('no pinned fingerprint for target'))
        return
      }
      const cert = socket.getPeerCertificate()
      if (!cert?.raw || !fingerprintMatches(cert.raw, expectedFingerprint)) {
        fail(new Error('certificate fingerprint mismatch'))
        return
      }
      settled = true
      socket.removeListener('error', fail)
      callback?.(null, socket)
    })
    return undefined
  }
}

/** Pooled HTTPS agent whose every socket goes through `pinnedConnection`. */
class PinnedAgent extends https.Agent {
  private readonly connect: ReturnType<typeof pinnedConnection>

  constructor(fingerprint: string) {
    super({ keepAlive: true, maxSockets: 64 })
    this.connect = pinnedConnection(fingerprint)
  }

  override createConnection(options: http.ClientRequestArgs, callback?: ConnectionCallback): undefined {
    return this.connect(options, callback)
  }
}

/** Rebuilt whenever the target changes, so a stale pin can never be reused. */
let tlsAgent: https.Agent | null = null

function transportFor(target: ProxyTarget) {
  if (!target.tls) return { mod: http, agent }
  if (!tlsAgent) tlsAgent = new PinnedAgent(target.certFingerprint ?? '')
  return { mod: https, agent: tlsAgent }
}

let server: http.Server | null = null
// Spliced websocket pairs. Upgrade sockets detach from the agent, so nothing
// else tracks them — and they MUST be dropped when the target changes, or a
// socket bound to the previous device would outlive a switch.
const upgrades = new Set<net.Socket>()
let listenPort: number | null = null
let ready: Promise<number> | null = null
let target: ProxyTarget | null = null
let portFilePath = ''
let onUpstreamFailure: ((failedTarget: ProxyTarget) => void) | null = null
let recentFailures: number[] = []

/**
 * Report a dead active route after more than one connection-level failure.
 * One cancelled request or websocket is ordinary renderer lifecycle; two
 * failures close together are strong evidence that the route itself died.
 */
export function setProxyFailureListener(fn: (failedTarget: ProxyTarget) => void): void {
  onUpstreamFailure = fn
}

function reportUpstreamSuccess(): void {
  recentFailures = []
}

function reportUpstreamFailure(failedTarget: ProxyTarget): void {
  if (target !== failedTarget || !failedTarget.tls) return
  const now = Date.now()
  recentFailures = [...recentFailures.filter((at) => now - at < 4000), now]
  if (recentFailures.length < 2) return
  recentFailures = []
  onUpstreamFailure?.(failedTarget)
}

/** Bound connection establishment without imposing an idle timeout on media. */
function boundConnectionEstablishment(req: http.ClientRequest): void {
  req.once('socket', (socket) => {
    if (!(socket as net.Socket).connecting) return
    socket.setTimeout(10000, () => socket.destroy(new Error('upstream connect timeout')))
    const connected = () => socket.setTimeout(0)
    if (socket instanceof tls.TLSSocket) socket.once('secureConnect', connected)
    else socket.once('connect', connected)
  })
}

export function getProxyPort(): number | null {
  return listenPort
}

/** Resolves once the proxy is bound. Callers need the port, not the ordering. */
export function waitForProxyPort(): Promise<number> {
  if (!ready) throw new Error('Proxy not started')
  return ready
}

export function getProxyTarget(): ProxyTarget | null {
  return target
}

/**
 * Point the proxy at a backend. Safe to call before or after start; requests
 * arriving with no target get a 503 so the renderer can render a connecting
 * state instead of a hard failure.
 */
export function setProxyTarget(next: ProxyTarget | null): void {
  const changed =
    target?.host !== next?.host ||
    target?.port !== next?.port ||
    target?.session !== next?.session ||
    target?.certFingerprint !== next?.certFingerprint
  target = next
  if (changed) {
    recentFailures = []
    dropUpgrades()
    tlsAgent?.destroy()
    tlsAgent = null
  }
  log.info('proxy', next ? `Target set to ${next.host}:${next.port}` : 'Target cleared')
}

function dropUpgrades(): void {
  for (const socket of upgrades) socket.destroy()
  upgrades.clear()
}

/**
 * Drop hop-by-hop headers and anything named by Connection. Applied in both
 * directions: request headers going upstream and response headers coming
 * back, since each hop negotiates its own connection semantics.
 */
function stripHopByHop(headers: http.IncomingHttpHeaders): http.OutgoingHttpHeaders {
  const connectionTokens = new Set(
    String(headers.connection ?? '')
      .split(',')
      .map((token) => token.trim().toLowerCase())
      .filter(Boolean),
  )

  const out: http.OutgoingHttpHeaders = {}
  for (const [name, value] of Object.entries(headers)) {
    const lower = name.toLowerCase()
    if (HOP_BY_HOP.has(lower) || connectionTokens.has(lower)) continue
    if (value !== undefined) out[name] = value
  }
  return out
}

/**
 * Strip hop-by-hop headers and anything named by Connection, then re-point
 * Host at the upstream. Everything else (Range, X-Profile-ID, X-Profile-PIN,
 * Origin, conditional-request headers) passes through untouched.
 */
export function forwardHeaders(
  headers: http.IncomingHttpHeaders,
  upstream: ProxyTarget,
): http.OutgoingHttpHeaders {
  const out = stripHopByHop(headers)
  out.host = `${upstream.host}:${upstream.port}`
  // The renderer never holds this. Injecting it here is the whole reason the
  // proxy exists: <img> and <video> cannot set headers, so remote media would
  // otherwise be unauthenticated or need a cache-busting query token.
  if (upstream.session) out.authorization = `Bearer ${upstream.session}`
  return out
}

/**
 * Responses the proxy generates itself never reach the backend's CORS
 * middleware, so they carry their own headers. Without this the renderer
 * sees an opaque CORS failure instead of the status, and cannot tell
 * "connecting" from "broken".
 */
function corsHeadersFor(req: http.IncomingMessage): Record<string, string> {
  const origin = req.headers.origin
  if (!origin) return {}
  return {
    'access-control-allow-origin': origin,
    'access-control-allow-credentials': 'true',
    'access-control-allow-headers': '*',
    'access-control-allow-methods': '*',
  }
}

function unavailable(req: http.IncomingMessage, res: http.ServerResponse): void {
  res.writeHead(503, { 'content-type': 'application/json', ...corsHeadersFor(req) })
  res.end(JSON.stringify({ detail: 'No active device' }))
}

function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
  const upstream = target
  if (!upstream) {
    unavailable(req, res)
    return
  }

  const transport = transportFor(upstream)
  const proxied = transport.mod.request(
    {
      host: upstream.host,
      port: upstream.port,
      method: req.method,
      path: req.url,
      headers: forwardHeaders(req.headers, upstream),
      agent: transport.agent,
    },
    (upstreamRes) => {
      reportUpstreamSuccess()
      // Status verbatim: 206/416 for ranged media and 304 for conditional
      // thumbnail requests have to survive the hop intact. Headers too, minus
      // the per-connection ones — Node frames this hop itself.
      res.writeHead(upstreamRes.statusCode ?? 502, stripHopByHop(upstreamRes.headers))
      upstreamRes.pipe(res)
    },
  )
  boundConnectionEstablishment(proxied)

  proxied.on('error', (err) => {
    reportUpstreamFailure(upstream)
    log.warn('proxy', `Upstream error for ${req.method} ${req.url}: ${err}`)
    if (res.headersSent) {
      // Mid-stream: a JSON tail glued onto half an image is worse than a
      // truncated response the renderer can detect.
      res.destroy()
      return
    }
    res.writeHead(502, { 'content-type': 'application/json', ...corsHeadersFor(req) })
    res.end(JSON.stringify({ detail: 'Upstream unreachable' }))
  })

  // A renderer that cancels (scrubbing a video, leaving a grid) closes its
  // side; stop pulling from upstream rather than draining a stream nobody
  // will read. After a completed exchange the request is already done and
  // this is a no-op.
  res.on('close', () => proxied.destroy())

  // Piped, never buffered — uploads and large media must stream.
  req.pipe(proxied)
  req.on('error', () => proxied.destroy())
}

/**
 * WebSocket upgrades (/ws). Node gives us the raw client socket; we replay
 * the handshake upstream and splice the two sockets once it succeeds.
 */
function handleUpgrade(req: http.IncomingMessage, socket: net.Socket, head: Buffer): void {
  const upstream = target
  if (!upstream) {
    socket.end('HTTP/1.1 503 Service Unavailable\r\n\r\n')
    return
  }

  socket.on('error', () => socket.destroy())

  const headers = forwardHeaders(req.headers, upstream)
  // Re-add the two hop-by-hop headers that ARE the upgrade handshake.
  headers.connection = 'Upgrade'
  headers.upgrade = req.headers.upgrade ?? 'websocket'

  // Dialled through the same agent as ordinary requests so the pin applies;
  // Node detaches the socket from the pool once the upgrade completes.
  const transport = transportFor(upstream)
  const proxied = transport.mod.request({
    host: upstream.host,
    port: upstream.port,
    method: req.method,
    path: req.url,
    headers,
    agent: transport.agent,
  })
  boundConnectionEstablishment(proxied)

  proxied.on('upgrade', (upstreamRes, upstreamSocket, upstreamHead) => {
    reportUpstreamSuccess()
    const statusLine = `HTTP/1.1 ${upstreamRes.statusCode} ${upstreamRes.statusMessage}\r\n`
    const rawHeaders = Object.entries(upstreamRes.headers)
      .flatMap(([name, value]) => (Array.isArray(value) ? value.map((v) => [name, v]) : [[name, value]]))
      .map(([name, value]) => `${name}: ${value}\r\n`)
      .join('')
    socket.write(statusLine + rawHeaders + '\r\n')

    // Bytes either side read past the handshake before we spliced.
    if (upstreamHead?.length) socket.write(upstreamHead)
    if (head?.length) upstreamSocket.write(head)

    // A half-open splice leaks both sockets, so either end closing tears the
    // pair down.
    upgrades.add(socket)
    upgrades.add(upstreamSocket)
    const teardown = () => {
      upgrades.delete(socket)
      upgrades.delete(upstreamSocket)
      socket.destroy()
      upstreamSocket.destroy()
    }
    socket.on('close', teardown)
    socket.on('error', teardown)
    upstreamSocket.on('close', () => {
      reportUpstreamFailure(upstream)
      teardown()
    })
    upstreamSocket.on('error', teardown)

    socket.pipe(upstreamSocket)
    upstreamSocket.pipe(socket)
  })

  proxied.on('response', () => {
    // Upstream declined the upgrade.
    socket.end('HTTP/1.1 502 Bad Gateway\r\n\r\n')
  })

  proxied.on('error', (err) => {
    reportUpstreamFailure(upstream)
    log.warn('proxy', `Upgrade failed for ${req.url}: ${err}`)
    socket.end('HTTP/1.1 502 Bad Gateway\r\n\r\n')
  })

  proxied.end()
}

function readRememberedPort(): number | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(portFilePath, 'utf8'))
    const port = parsed?.port
    return Number.isInteger(port) && port > 1024 && port < 65536 ? port : null
  } catch {
    return null
  }
}

function rememberPort(port: number): void {
  try {
    const tmp = portFilePath + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify({ port }, null, 2))
    fs.renameSync(tmp, portFilePath)
  } catch {
    // Best-effort: a lost port file costs one cold cache, not correctness.
  }
}

function listen(port: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const onError = (err: NodeJS.ErrnoException) => {
      server?.removeListener('listening', onListening)
      reject(err)
    }
    const onListening = () => {
      server?.removeListener('error', onError)
      const address = server?.address()
      resolve(typeof address === 'object' && address ? address.port : port)
    }
    server?.once('error', onError)
    server?.once('listening', onListening)
    server?.listen(port, '127.0.0.1')
  })
}

/**
 * Start the proxy, preferring the port used last time so the renderer's
 * origin — and therefore Chromium's disk cache — survives a restart. If that
 * port is taken (another sandbox, or unrelated software), fall back to an
 * ephemeral one and remember it instead.
 */
export function startProxy(dataDir: string): Promise<number> {
  if (ready) return ready
  ready = bind(dataDir)
  return ready
}

async function bind(dataDir: string): Promise<number> {
  fs.mkdirSync(dataDir, { recursive: true })
  portFilePath = path.join(dataDir, 'proxy-port.json')

  server = http.createServer(handleRequest)
  server.on('upgrade', handleUpgrade)

  const remembered = readRememberedPort()
  if (remembered !== null) {
    try {
      listenPort = await listen(remembered)
      log.info('proxy', `Listening on 127.0.0.1:${listenPort} (remembered)`)
      return listenPort
    } catch (err) {
      log.info('proxy', `Remembered port ${remembered} unavailable (${err}); picking a new one`)
    }
  }

  listenPort = await listen(0)
  rememberPort(listenPort)
  log.info('proxy', `Listening on 127.0.0.1:${listenPort} (new)`)
  return listenPort
}

export function stopProxy(): void {
  // Keep-alive sockets and spliced websockets would otherwise hold the
  // listener (and the process) open well past close().
  dropUpgrades()
  server?.closeAllConnections()
  server?.close()
  agent.destroy()
  tlsAgent?.destroy()
  tlsAgent = null
  server = null
  listenPort = null
  ready = null
  target = null
  recentFailures = []
  onUpstreamFailure = null
}
