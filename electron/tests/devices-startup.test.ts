import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import crypto from 'node:crypto'
import fs from 'node:fs'
import https from 'node:https'
import http from 'node:http'
import path from 'node:path'
import { build } from 'esbuild'
import { makeScratchDir } from './scratch.mjs'

for (const accepted of [true, false]) {
  test(`cached remote startup ${accepted ? 'connects before Python' : 'keeps revoked sessions off the proxy'}`, async () => {
    const scratch = makeScratchDir('devices-startup-')
    const keyPath = path.join(scratch.dir, 'key.pem')
    const certPath = path.join(scratch.dir, 'cert.pem')
    execFileSync('openssl', ['req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
      '-nodes', '-keyout', keyPath, '-out', certPath, '-days', '1', '-subj', '/CN=remote-test'], { stdio: 'ignore' })
    const cert = fs.readFileSync(certPath)
    const fingerprint = crypto.createHash('sha256').update(new crypto.X509Certificate(cert).raw).digest('hex')
    const requests: string[] = []
    const server = https.createServer({ key: fs.readFileSync(keyPath), cert }, (req, res) => {
      requests.push(req.url!)
      if (req.url === '/multi-device/ping') res.end(JSON.stringify({ deviceId: 'remote' }))
      else if (req.url === '/multi-device/session') res.end(JSON.stringify({ session: 'new-session' }))
      else {
        assert.equal(req.headers.authorization, 'Bearer saved-session')
        res.writeHead(accepted ? 200 : 401).end('{}')
      }
    })
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    try {
      const port = (server.address() as { port: number }).port
      fs.writeFileSync(path.join(scratch.dir, 'devices.json'), JSON.stringify({
        activeDeviceId: 'remote', sessions: { remote: Buffer.from('saved-session').toString('base64') },
        devices: [{ deviceId: 'remote', name: 'Remote', serving: true, certFingerprint: fingerprint,
          routes: [{ kind: 'lan', host: '127.0.0.1', port }] }], preferredRoutes: {},
      }))
      const outfile = path.join(scratch.dir, 'devices.cjs')
      await build({
        stdin: { contents: `export * from './src/devices.ts'; export { getProxyTarget } from './src/proxy.ts'`,
          resolveDir: path.resolve(import.meta.dirname, '..'), loader: 'ts' },
        outfile, bundle: true, platform: 'node', format: 'cjs',
        plugins: [{ name: 'test-keyring', setup(build) {
          build.onResolve({ filter: /^electron$/ }, () => ({ path: 'electron', namespace: 'test' }))
          build.onLoad({ filter: /.*/, namespace: 'test' }, () => ({ contents:
            `export const safeStorage = { isEncryptionAvailable: () => true, decryptString: b => b.toString(), encryptString: s => Buffer.from(s) }` }))
        } }],
      })
      const devices = createRequire(import.meta.url)(outfile)
      devices.initDevices(scratch.dir)
      devices.startCachedDeviceConnection()
      const deadline = Date.now() + 3000
      while (!requests.includes('/api/profiles') && Date.now() < deadline) await new Promise(r => setTimeout(r, 10))
      await new Promise(r => setTimeout(r, 30))
      assert.deepEqual(requests, ['/multi-device/ping', '/api/profiles'])
      assert.equal(devices.getConnectionState(), accepted ? 'ready' : 'connecting')
      assert.equal(devices.getProxyTarget()?.session ?? null, accepted ? 'saved-session' : null)
      if (!accepted) {
        const localRequests: string[] = []
        const local = http.createServer((req, res) => {
          localRequests.push(req.url!)
          res.setHeader('content-type', 'application/json')
          res.end(JSON.stringify(req.url === '/api/multi-device/connect-token'
            ? { idToken: 'test-account', selfDeviceId: 'local' }
            : { registryError: 'test registry unavailable' }))
        })
        await new Promise<void>(resolve => local.listen(0, '127.0.0.1', resolve))
        try {
          devices.setLocalBackendPort((local.address() as { port: number }).port)
          const deadline = Date.now() + 3000
          while (devices.getConnectionState() !== 'ready' && Date.now() < deadline) await new Promise(r => setTimeout(r, 10))
          assert.equal(devices.getConnectionState(), 'ready')
          assert.equal(devices.getProxyTarget().session, 'new-session')
          assert(localRequests.includes('/api/multi-device/connect-token'))
          assert(requests.includes('/multi-device/session'))
        } finally {
          await new Promise<void>(resolve => local.close(() => resolve()))
        }
      }
    } finally {
      await new Promise<void>(resolve => server.close(() => resolve()))
      scratch.cleanup()
    }
  })
}
