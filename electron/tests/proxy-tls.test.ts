/**
 * Certificate pinning for remote (HTTPS) targets.
 *
 * Serving devices present self-signed certificates, so CA verification is off
 * and the pinned SHA-256 fingerprint is the ONLY thing standing between the
 * session bearer / media bytes and whoever answers on that address. These
 * tests hold a real TLS server up against the proxy and check that a wrong
 * fingerprint refuses the connection before a single request byte is sent.
 */
import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'
import { execFileSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import https from 'node:https'
import net from 'node:net'
import path from 'node:path'

import {
  pinnedConnection,
  setProxyFailureListener,
  setProxyTarget,
  startProxy,
  stopProxy,
} from '../src/proxy.ts'
import { makeScratchDir } from './scratch.mjs'

const scratchCleanups = new Set<() => void>()

function tmpDir(): string {
  const scratch = makeScratchDir('proxy-tls-test-')
  scratchCleanups.add(scratch.cleanup)
  return scratch.dir
}

afterEach(() => {
  stopProxy()
  for (const cleanup of scratchCleanups) cleanup()
  scratchCleanups.clear()
})

interface Identity {
  key: string
  cert: string
  /** Lowercase hex SHA-256 of the certificate DER — what the registry publishes. */
  fingerprint: string
}

function hasOpenssl(): boolean {
  try {
    execFileSync('openssl', ['version'], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

/**
 * A throwaway self-signed identity, the same shape the Python side produces
 * (backend/multi_device/identity.py). Node can parse X.509 but not mint it,
 * so this shells out to openssl; the suite skips where that is missing.
 */
function selfSigned(dir: string, cn: string): Identity {
  const key = path.join(dir, `${cn}-key.pem`)
  const cert = path.join(dir, `${cn}-cert.pem`)
  execFileSync(
    'openssl',
    [
      'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
      '-keyout', key, '-out', cert, '-days', '1', '-subj', `/CN=${cn}`,
      '-addext', 'subjectAltName=IP:127.0.0.1',
    ],
    { stdio: 'ignore' },
  )
  const certPem = fs.readFileSync(cert, 'utf8')
  const der = new crypto.X509Certificate(certPem).raw
  return {
    key: fs.readFileSync(key, 'utf8'),
    cert: certPem,
    fingerprint: crypto.createHash('sha256').update(der).digest('hex'),
  }
}

interface TlsUpstream {
  port: number
  server: https.Server
  /** Every request the handler saw. Stays empty when the pin refuses. */
  requests: http.IncomingMessage[]
  /** Every upgrade the server saw. */
  upgrades: http.IncomingMessage[]
  sockets: Set<net.Socket>
}

function tlsUpstream(
  id: Identity,
  handler: (req: http.IncomingMessage, res: http.ServerResponse) => void,
): Promise<TlsUpstream> {
  const requests: http.IncomingMessage[] = []
  const upgrades: http.IncomingMessage[] = []
  const sockets = new Set<net.Socket>()
  const server = https.createServer({ key: id.key, cert: id.cert }, (req, res) => {
    requests.push(req)
    handler(req, res)
  })
  server.on('upgrade', (req, socket, head) => {
    upgrades.push(req)
    sockets.add(socket)
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
    if (head?.length) socket.write(head)
    socket.on('data', (d) => socket.write(d))
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      resolve({ port: (server.address() as net.AddressInfo).port, server, requests, upgrades, sockets })
    })
  })
}

function closeUpstream(up: TlsUpstream): Promise<void> {
  for (const socket of up.sockets) socket.destroy()
  return new Promise((resolve) => {
    up.server.closeAllConnections()
    up.server.close(() => resolve())
  })
}

function get(port: number, reqPath: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: reqPath }, (res) => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => (body += chunk))
      res.on('end', () => resolve({ status: res.statusCode!, body }))
    })
    req.on('error', reject)
    req.end()
  })
}

/** Replay a websocket handshake through the proxy; resolves with the status line. */
function upgradeThrough(port: number): Promise<{ status: number; echoed?: string }> {
  return new Promise((resolve, reject) => {
    const req = http.request({
      host: '127.0.0.1',
      port,
      path: '/ws',
      headers: { connection: 'Upgrade', upgrade: 'websocket' },
    })
    req.on('upgrade', (res, socket) => {
      socket.setEncoding('utf8')
      socket.once('data', (d: string) => {
        socket.destroy()
        resolve({ status: res.statusCode!, echoed: d })
      })
      socket.write('ping')
    })
    // A refused upgrade comes back as an ordinary response (502).
    req.on('response', (res) => {
      res.resume()
      resolve({ status: res.statusCode! })
    })
    req.on('error', reject)
    req.end()
  })
}

const skip = hasOpenssl() ? false : 'openssl not on PATH; cannot mint a test certificate'

// A well-formed fingerprint that matches no certificate: what an attacker's
// cert looks like against the registry's published value.
const WRONG_FINGERPRINT = '0'.repeat(64)

test('forwards to a TLS upstream whose certificate matches the pin', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'device')
  const up = await tlsUpstream(id, (req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ auth: req.headers.authorization ?? null }))
  })

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port, tls: true, certFingerprint: id.fingerprint, session: 'sess-1' })

  const res = await get(port, '/api/settings')
  assert.equal(res.status, 200)
  // The bearer reaches the device only once the pin has held.
  assert.equal(JSON.parse(res.body).auth, 'Bearer sess-1')
  assert.equal(up.requests.length, 1)

  stopProxy()
  await closeUpstream(up)
})

test('refuses a TLS upstream whose certificate does not match the pin', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'impostor')
  const up = await tlsUpstream(id, (_req, res) => res.end('leaked'))

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port, tls: true, certFingerprint: WRONG_FINGERPRINT, session: 'sess-1' })

  const res = await get(port, '/api/settings')
  assert.equal(res.status, 502)
  assert.equal(JSON.parse(res.body).detail, 'Upstream unreachable')
  // The whole point: nothing was sent, so the impostor never saw a request —
  // no path, no bearer, no bytes.
  assert.equal(up.requests.length, 0)

  stopProxy()
  await closeUpstream(up)
})

test('reports an active remote route after two connection-level failures', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'failed-route')
  const up = await tlsUpstream(id, (_req, res) => res.end('unused'))
  const deadPort = up.port
  await closeUpstream(up)

  const port = await startProxy(dir)
  const failed = new Promise<void>((resolve) => {
    setProxyFailureListener(() => resolve())
  })
  setProxyTarget({
    host: '127.0.0.1',
    port: deadPort,
    tls: true,
    certFingerprint: id.fingerprint,
  })

  assert.equal((await get(port, '/api/settings')).status, 502)
  assert.equal((await get(port, '/api/settings')).status, 502)
  await failed
})

test('refuses a TLS upstream when the target carries no fingerprint at all', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'unpinned')
  const up = await tlsUpstream(id, (_req, res) => res.end('leaked'))

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port, tls: true, session: 'sess-1' })

  const res = await get(port, '/api/settings')
  assert.equal(res.status, 502)
  assert.equal(up.requests.length, 0)

  stopProxy()
  await closeUpstream(up)
})

test('splices a websocket upgrade to a pinned TLS upstream', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'device')
  const up = await tlsUpstream(id, () => {})

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port, tls: true, certFingerprint: id.fingerprint })

  const result = await upgradeThrough(port)
  assert.equal(result.status, 101)
  assert.equal(result.echoed, 'ping')
  assert.equal(up.upgrades.length, 1)

  stopProxy()
  await closeUpstream(up)
})

test('refuses a websocket upgrade when the TLS upstream fails the pin', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'impostor')
  const up = await tlsUpstream(id, () => {})

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port, tls: true, certFingerprint: WRONG_FINGERPRINT })

  const result = await upgradeThrough(port)
  assert.equal(result.status, 502)
  assert.equal(up.upgrades.length, 0)
  assert.equal(up.requests.length, 0)

  stopProxy()
  await closeUpstream(up)
})

// devices.ts dials serving devices directly (probe, session bootstrap) with
// the same factory but no agent; that path has to refuse just as hard, since
// it is the one that carries the account's ID token.
test('pinnedConnection as a request createConnection enforces the pin', { skip }, async () => {
  const dir = tmpDir()
  const id = selfSigned(dir, 'device')
  const up = await tlsUpstream(id, (_req, res) => res.end('ok'))

  const direct = (fingerprint: string) =>
    new Promise<{ status?: number; error?: Error }>((resolve) => {
      const req = https.request(
        { host: '127.0.0.1', port: up.port, path: '/multi-device/ping', createConnection: pinnedConnection(fingerprint) },
        (res) => {
          res.resume()
          res.on('end', () => resolve({ status: res.statusCode }))
        },
      )
      req.on('error', (error) => resolve({ error }))
      req.end()
    })

  const good = await direct(id.fingerprint)
  assert.equal(good.status, 200)
  assert.equal(up.requests.length, 1)

  const bad = await direct(WRONG_FINGERPRINT)
  assert.match(bad.error?.message ?? '', /fingerprint mismatch/)
  assert.equal(up.requests.length, 1, 'impostor handshake must not turn into a request')

  await closeUpstream(up)
})

/**
 * A blackholed route — a laptop asleep on a Wi-Fi address it still
 * advertises — accepts nothing and refuses nothing. The pinned connector is
 * the only thing that can bound that wait, because the request has no socket
 * until the handshake succeeds, and that one failure is conclusive: the proxy
 * must report it at once rather than wait for a second one.
 */
test('a connect that never completes fails within the bound and reports the route dead', { skip }, async () => {
  const dir = tmpDir()
  // Accepts TCP and then says nothing, so the TLS handshake hangs forever.
  // A paused socket never sees the peer's FIN either, so teardown has to
  // destroy them by hand or server.close() waits for them forever.
  const silentSockets = new Set<net.Socket>()
  const silent = net.createServer((socket) => {
    silentSockets.add(socket)
    socket.pause()
  })
  const silentPort = await new Promise<number>((resolve) =>
    silent.listen(0, '127.0.0.1', () => resolve((silent.address() as net.AddressInfo).port)),
  )

  const started = Date.now()
  const err = await new Promise<Error>((resolve) => {
    const req = https.request(
      { host: '127.0.0.1', port: silentPort, path: '/', createConnection: pinnedConnection(WRONG_FINGERPRINT, 300) },
      () => resolve(new Error('unexpected response')),
    )
    req.on('error', resolve)
    req.end()
  })
  assert.equal(err.message, 'upstream connect timeout')
  assert.ok(Date.now() - started < 5000, 'failed within the bound, not the kernel timeout')

  const failures: number[] = []
  setProxyFailureListener(() => failures.push(Date.now()))
  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: silentPort, tls: true, certFingerprint: WRONG_FINGERPRINT, session: 's' })
  const res = await get(port, '/api/profiles/p/verify-pin')
  assert.equal(res.status, 502)
  // One connect-level failure is enough; no second request was needed.
  assert.equal(failures.length, 1)

  stopProxy()
  setProxyFailureListener(() => {})
  for (const socket of silentSockets) socket.destroy()
  await new Promise<void>((resolve) => silent.close(() => resolve()))
})
