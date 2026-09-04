import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'
import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import path from 'node:path'

import { forwardHeaders, getProxyPort, setProxyTarget, startProxy, stopProxy } from '../src/proxy.ts'
import { makeScratchDir } from './scratch.mjs'

const scratchCleanups = new Set<() => void>()

function tmpDir(): string {
  const scratch = makeScratchDir('proxy-test-')
  scratchCleanups.add(scratch.cleanup)
  return scratch.dir
}

afterEach(() => {
  stopProxy()
  for (const cleanup of scratchCleanups) cleanup()
  scratchCleanups.clear()
})

interface Upstream {
  port: number
  server: http.Server
  /** Sockets handed off by 'upgrade'; http.Server stops accounting for these. */
  upgraded: Set<net.Socket>
}

/** An upstream that echoes back what the proxy actually sent it. */
function upstream(
  handler: (req: http.IncomingMessage, res: http.ServerResponse) => void,
): Promise<Upstream> {
  const server = http.createServer(handler)
  const upgraded = new Set<net.Socket>()
  server.on('upgrade', (_req, socket) => upgraded.add(socket))
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      resolve({ port: (server.address() as net.AddressInfo).port, server, upgraded })
    })
  })
}

/** Shut an upstream down hard, including any sockets it upgraded. */
function closeUpstream(up: Upstream): Promise<void> {
  for (const socket of up.upgraded) socket.destroy()
  up.upgraded.clear()
  return new Promise((resolve) => {
    up.server.closeAllConnections()
    up.server.close(() => resolve())
  })
}

function get(
  port: number,
  reqPath: string,
  headers: Record<string, string> = {},
): Promise<{ status: number; headers: http.IncomingHttpHeaders; body: string }> {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: reqPath, headers }, (res) => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => (body += chunk))
      res.on('end', () => resolve({ status: res.statusCode!, headers: res.headers, body }))
    })
    req.on('error', reject)
    req.end()
  })
}

test('forwardHeaders drops hop-by-hop headers and re-points Host', () => {
  const out = forwardHeaders(
    {
      host: '127.0.0.1:1111',
      connection: 'keep-alive, x-custom-hop',
      'keep-alive': 'timeout=5',
      'transfer-encoding': 'chunked',
      'x-custom-hop': 'should-be-dropped',
      'x-profile-id': 'profile-abc123',
      range: 'bytes=0-1023',
      origin: 'app://stimma',
    },
    { host: '127.0.0.1', port: 4242 },
  )

  assert.equal(out.host, '127.0.0.1:4242')
  assert.equal(out.connection, undefined)
  assert.equal(out['keep-alive'], undefined)
  assert.equal(out['transfer-encoding'], undefined)
  // Named by Connection, so per-connection too.
  assert.equal(out['x-custom-hop'], undefined)
  // Everything the app depends on survives.
  assert.equal(out['x-profile-id'], 'profile-abc123')
  assert.equal(out.range, 'bytes=0-1023')
  assert.equal(out.origin, 'app://stimma')
})

test('503s with no target rather than failing the connection', async () => {
  const dir = tmpDir()
  const port = await startProxy(dir)
  setProxyTarget(null)

  const res = await get(port, '/api/settings')
  assert.equal(res.status, 503)
  assert.equal(JSON.parse(res.body).detail, 'No active device')

  stopProxy()
  fs.rmSync(dir, { recursive: true, force: true })
})

test('forwards method, path, headers, and ranged responses', async () => {
  const dir = tmpDir()
  const seen: { url?: string; headers?: http.IncomingHttpHeaders } = {}
  const up = await upstream((req, res) => {
    seen.url = req.url
    seen.headers = req.headers
    // Mimic a ranged thumbnail/video response.
    res.writeHead(206, {
      'content-type': 'image/webp',
      'content-range': 'bytes 0-3/1024',
      'accept-ranges': 'bytes',
    })
    res.end('abcd')
  })

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port })

  const res = await get(port, '/api/db/guid-1/thumbnail/hash?size=256', {
    'x-profile-id': 'profile-abc123',
    range: 'bytes=0-3',
  })

  assert.equal(seen.url, '/api/db/guid-1/thumbnail/hash?size=256')
  assert.equal(seen.headers?.['x-profile-id'], 'profile-abc123')
  assert.equal(seen.headers?.range, 'bytes=0-3')
  // 206 and the range headers have to survive verbatim or media breaks.
  assert.equal(res.status, 206)
  assert.equal(res.headers['content-range'], 'bytes 0-3/1024')
  assert.equal(res.body, 'abcd')

  stopProxy()
  await closeUpstream(up)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('streams a body incrementally instead of buffering it', async () => {
  const dir = tmpDir()
  const up = await upstream((_req, res) => {
    res.writeHead(200, { 'content-type': 'text/plain' })
    res.write('first')
    // Flush a second chunk only after the client has seen the first.
    setTimeout(() => res.end('second'), 50)
  })

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port })

  const chunks: string[] = await new Promise((resolve, reject) => {
    const acc: string[] = []
    const req = http.request({ host: '127.0.0.1', port, path: '/stream' }, (res) => {
      res.setEncoding('utf8')
      res.on('data', (c) => acc.push(c))
      res.on('end', () => resolve(acc))
    })
    req.on('error', reject)
    req.end()
  })

  assert.ok(chunks.length >= 2, `expected multiple chunks, got ${JSON.stringify(chunks)}`)
  assert.equal(chunks.join(''), 'firstsecond')

  stopProxy()
  await closeUpstream(up)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('502s when the upstream is gone', async () => {
  const dir = tmpDir()
  const up = await upstream((_req, res) => res.end('ok'))
  const deadPort = up.port
  await closeUpstream(up)

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: deadPort })

  const res = await get(port, '/api/settings')
  assert.equal(res.status, 502)

  stopProxy()
  fs.rmSync(dir, { recursive: true, force: true })
})

test('splices a websocket upgrade end to end', async () => {
  const dir = tmpDir()
  const up = await upstream(() => {})
  up.server.on('upgrade', (_req, socket, head) => {
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
    if (head?.length) socket.write(head)
    // Echo, so we prove both directions are spliced.
    socket.on('data', (d) => socket.write(d))
  })

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: up.port })

  const result: string = await new Promise((resolve, reject) => {
    const req = http.request({
      host: '127.0.0.1',
      port,
      path: '/ws',
      headers: { connection: 'Upgrade', upgrade: 'websocket' },
    })
    req.on('upgrade', (res, socket) => {
      assert.equal(res.statusCode, 101)
      socket.setEncoding('utf8')
      socket.once('data', (d: string) => {
        socket.destroy()
        resolve(d)
      })
      socket.write('ping')
    })
    req.on('error', reject)
    req.end()
  })

  assert.equal(result, 'ping')

  stopProxy()
  await closeUpstream(up)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('503s an upgrade with no target instead of hanging', async () => {
  const dir = tmpDir()
  const port = await startProxy(dir)
  setProxyTarget(null)

  const status: string = await new Promise((resolve, reject) => {
    const socket = net.connect(port, '127.0.0.1', () => {
      socket.write('GET /ws HTTP/1.1\r\nHost: x\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n')
    })
    socket.setEncoding('utf8')
    socket.once('data', (d: string) => {
      socket.destroy()
      resolve(d.split('\r\n')[0])
    })
    socket.on('error', reject)
  })

  assert.match(status, /503/)

  stopProxy()
  fs.rmSync(dir, { recursive: true, force: true })
})

test('reuses the same port across restarts so the renderer origin is stable', async () => {
  const dir = tmpDir()

  const first = await startProxy(dir)
  stopProxy()

  const second = await startProxy(dir)
  assert.equal(second, first, 'proxy port must survive a restart to keep the HTTP cache warm')
  stopProxy()

  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'proxy-port.json'), 'utf8')).port, first)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('falls back to a fresh port when the remembered one is taken', async () => {
  const dir = tmpDir()

  const first = await startProxy(dir)
  stopProxy()

  // Squat on the remembered port, as another sandbox or app would.
  const squatter = net.createServer()
  await new Promise<void>((resolve) => squatter.listen(first, '127.0.0.1', resolve))

  const second = await startProxy(dir)
  assert.notEqual(second, first)
  assert.equal(getProxyPort(), second)
  // The new port is remembered in turn.
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'proxy-port.json'), 'utf8')).port, second)

  stopProxy()
  await new Promise((resolve) => squatter.close(resolve))
  fs.rmSync(dir, { recursive: true, force: true })
})

/**
 * uvicorn closes idle keep-alive connections; a pooled socket it has just
 * closed fails on first use with "socket hang up". That is a pool artefact,
 * not a dead route: a bodiless request must be replayed on a fresh
 * connection, the renderer must see the real answer, and the failure
 * listener must stay quiet.
 */
test('retries a bodiless request once when a pooled socket was closed upstream', async () => {
  const dir = tmpDir()
  let hits = 0
  let connections = 0
  const upstream = http.createServer((req, res) => {
    hits += 1
    // Close right behind the response. The proxy's pool learns of the FIN a
    // task later than the renderer learns of the response, so a request
    // issued in between is guaranteed to reuse the dead socket. (res.socket
    // is detached by the time 'finish' fires; hold the socket from req.)
    const socket = req.socket
    res.on('finish', () => socket.end())
    res.writeHead(200, { 'content-type': 'text/plain', connection: 'keep-alive' })
    res.end(`hit ${hits}`)
  })
  upstream.on('connection', () => (connections += 1))
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve))
  const upstreamPort = (upstream.address() as net.AddressInfo).port

  const port = await startProxy(dir)
  setProxyTarget({ host: '127.0.0.1', port: upstreamPort })

  const first = await get(port, '/api/one')
  assert.equal(first.status, 200)
  const second = await get(port, '/api/two')
  assert.equal(second.status, 200, 'the replayed request reaches upstream')
  assert.equal(second.body, 'hit 2')
  assert.equal(connections, 2, 'the retry opened a fresh connection')

  stopProxy()
  await new Promise<void>((resolve) => upstream.close(() => resolve()))
})
