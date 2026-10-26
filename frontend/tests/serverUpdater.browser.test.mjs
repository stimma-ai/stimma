import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'

const buildResult = await build({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), logLevel: 'silent', plugins: [vue()],
  define: { 'process.env.NODE_ENV': '"production"' },
  css: { postcss: { plugins: [] } },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/serverUpdater.ts', import.meta.url)), formats: ['iife'], name: 'ServerUpdaterTest',
  } },
})
const script = (Array.isArray(buildResult) ? buildResult : [buildResult]).flatMap(r => r.output).find(item => item.type === 'chunk').code

const READY = { headless: true, version: '1.0.0', availableVersion: '1.1.0', status: 'ready', bootstrapVersion: '1', serverStartedAt: 10 }

/**
 * A connected client against a fake headless server. `server.status` is what
 * /api/headless/status answers; null means the server is down (restarting).
 */
async function fixture(t, { desktop = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  page.setDefaultTimeout(10000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  // `gate`, when set, holds status responses until it resolves.
  const server = { status: { ...READY }, statusRequests: 0, commands: [], sockets: new Set(), gate: null }
  await page.clock.install()
  await page.routeWebSocket('**/ws', ws => {
    server.sockets.add(ws)
    ws.onClose(() => server.sockets.delete(ws))
  })
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (url.pathname === '/api/headless/status') {
      server.statusRequests++
      if (server.gate) await server.gate
      if (!server.status) return route.abort('connectionrefused')
      return route.fulfill({ json: server.status })
    }
    const command = url.pathname.match(/^\/api\/headless\/(check|update|restart)$/)?.[1]
    if (command && route.request().method() === 'POST') {
      server.commands.push(command)
      return route.fulfill({ json: server.status })
    }
    return route.abort()
  })
  await page.goto('http://updater.test/')
  if (desktop) {
    // A non-owner desktop window: the updater lives in another window that
    // this page plays through the shared BroadcastChannel.
    await page.evaluate(() => {
      const calls = { getBackendPort: async () => 1, mdGetState: async () => ({ activeDeviceId: 'local', devices: [], connectionState: 'ready' }),
        mdOnConnectionState: () => () => {}, mdRefreshDevices: async () => [], mdLocalStatus: async () => ({}), getAppVersion: async () => '1.0.0' }
      window.stimmaDesktop = new Proxy({ kind: 'electron', ...calls }, { get: (target, key) => key in target ? target[key] : async () => null })
      window.ownerMessages = []
      window.ownerState = { hasUpdate: false, availableVersion: null, stagedVersion: null, pendingApply: null,
        isDownloading: false, isChecking: false, lastCheckedAt: 't0' }
      const owner = window.owner = new BroadcastChannel('stimma-updater')
      window.publishOwner = patch => { Object.assign(window.ownerState, patch); owner.postMessage({ type: 'state', state: { ...window.ownerState } }) }
      owner.onmessage = event => {
        window.ownerMessages.push(event.data.type)
        if (event.data.type === 'request-state') window.publishOwner({})
        // A forwarded check that runs for a long time before reporting.
        if (event.data.type === 'check') window.publishOwner({ isChecking: true })
      }
    })
  }
  await load(page, desktop)
  await page.waitForFunction(() => window.serverUpdater.snapshot().version === '1.0.0')
  return { page, server, snapshot: () => page.evaluate(() => window.serverUpdater.snapshot()) }
}

async function load(page, desktop = false) {
  await page.addScriptTag({ content: script })
  await page.evaluate(skipApiConfig => window.serverUpdater.start({ skipApiConfig }), desktop)
  await advance(page, 1000)
}

function setAppActive(page, active) {
  return page.evaluate(detail => window.dispatchEvent(new CustomEvent('stimma:app-active', { detail })), active)
}

/** Advance virtual time in steps, letting each step's real network round trips settle. */
async function advance(page, ms, step = Math.min(ms, ms >= 60_000 ? 10_000 : 1_000)) {
  for (let elapsed = 0; elapsed < ms; elapsed += step) {
    await page.clock.runFor(Math.min(step, ms - elapsed))
    await new Promise(resolve => setTimeout(resolve, 25))
  }
}

async function dropSockets(server) {
  for (const ws of [...server.sockets]) await ws.close()
}

test('an idle connected client does not poll server status every few seconds', async t => {
  const { page, server } = await fixture(t)
  const settled = server.statusRequests
  assert.ok(settled >= 1 && settled <= 2, `startup refreshes (${settled})`)
  await advance(page, 5 * 60_000)
  assert.equal(server.statusRequests, settled, 'no status requests during five idle minutes')
  await advance(page, 6 * 60_000)
  assert.equal(server.statusRequests, settled + 1, 'one slow backstop refresh')
})

test('an update polls through the restart to completion, then goes quiet', async t => {
  const { page, server, snapshot } = await fixture(t)
  await page.evaluate(() => window.serverUpdater.act('update'))
  assert.deepEqual(server.commands, ['update'])
  assert.equal((await snapshot()).pending?.action, 'update')

  const before = server.statusRequests
  await advance(page, 9_000)
  assert.ok(server.statusRequests - before >= 3, 'fast polling while the update is underway')

  server.status = { ...server.status, status: 'downloading' }
  await advance(page, 6_000)
  // The server goes down: status fails and the app socket drops.
  server.status = null
  await dropSockets(server)
  await advance(page, 20_000)
  assert.ok((await snapshot()).pending, 'a disconnect is not completion')

  server.status = { ...READY, version: '1.1.0', serverStartedAt: 11 }
  await advance(page, 4_000)
  await page.waitForFunction(() => window.serverUpdater.snapshot().pending === null)
  const done = await snapshot()
  assert.equal(done.version, '1.1.0')
  assert.equal(done.busy, false)

  await advance(page, 30_000)
  const quiet = server.statusRequests
  await advance(page, 5 * 60_000)
  assert.equal(server.statusRequests, quiet, 'idle cadence after completion')
})

test('a server restart is picked up from the reconnecting socket without idle polling', async t => {
  const { page, server, snapshot } = await fixture(t)
  await advance(page, 60_000)
  const before = server.statusRequests
  // Restarted outside this client (for example a scheduled update).
  server.status = { ...READY, version: '1.1.0', serverStartedAt: 12 }
  await dropSockets(server)
  await advance(page, 2_000)
  await page.waitForFunction(() => window.serverUpdater.snapshot().version === '1.1.0')
  assert.ok(server.statusRequests - before <= 2)
  assert.equal((await snapshot()).busy, false)
})

test('background and offline pause idle polling; returning refreshes once', async t => {
  const { page, server } = await fixture(t)
  const before = server.statusRequests
  await setAppActive(page, false)
  await advance(page, 25 * 60_000)
  await dropSockets(server) // Even a reconnect stays quiet while backgrounded.
  await advance(page, 2_000)
  assert.equal(server.statusRequests, before, 'no polling in the background')
  await setAppActive(page, true)
  await advance(page, 100)
  assert.equal(server.statusRequests, before + 1, 'one refresh on return')

  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await advance(page, 25 * 60_000)
  assert.equal(server.statusRequests, before + 1, 'no polling while offline')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await advance(page, 100)
  assert.equal(server.statusRequests, before + 2)
})

test('an idle response that arrives after backgrounding starts nothing more', async t => {
  const { page, server } = await fixture(t)
  let release
  server.gate = new Promise(resolve => { release = resolve })
  await dropSockets(server) // Reconnect wakes an idle refresh that is held in flight.
  await advance(page, 2_000)
  const started = server.statusRequests
  await setAppActive(page, false)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  server.gate = null
  release()
  await advance(page, 25 * 60_000)
  assert.equal(server.statusRequests, started)
})

test('a client update check makes the status view follow the server check', async t => {
  const { page, server } = await fixture(t)
  const before = server.statusRequests
  await page.evaluate(() => window.dispatchEvent(new Event('stimma:server-update-check-started')))
  await advance(page, 100)
  assert.equal(server.statusRequests, before + 1)
  await advance(page, 9_000)
  assert.ok(server.statusRequests - before >= 3, 'short fast follow-up while the check runs')
  await advance(page, 20_000)
  const quiet = server.statusRequests
  await advance(page, 5 * 60_000)
  assert.equal(server.statusRequests, quiet)
})

test('an update-all keeps being tracked while minimized and runs both stages', async t => {
  const { page, server, snapshot } = await fixture(t)
  await page.evaluate(() => window.serverUpdater.clientUpdaterReady())
  await page.evaluate(() => window.serverUpdater.act('update', true))
  assert.equal((await snapshot()).pending?.updateMachine, true)
  await setAppActive(page, false)
  await advance(page, 60_000)
  const minimized = server.statusRequests
  server.status = { ...READY, version: '1.1.0', serverStartedAt: 11 }
  await advance(page, 4_000)
  assert.ok(server.statusRequests > minimized)
  assert.equal((await snapshot()).pending?.serverFinished, true, 'server stage confirmed while minimized')
  // This browser has no client updater, so the follow-up finds nothing to
  // install and ends with its own window.
  await advance(page, 11 * 60_000)
  assert.equal((await snapshot()).pending, null)
  const quiet = server.statusRequests
  await advance(page, 25 * 60_000)
  assert.equal(server.statusRequests, quiet, 'idle and minimized: no polling')
})

test('transport failures past the grace do not discard update-all intent', async t => {
  const { page, server, snapshot } = await fixture(t)
  await page.evaluate(() => window.serverUpdater.act('update', true))
  // Unreachable for eleven minutes (or the OS froze the app): no answer.
  server.status = null
  await advance(page, 11 * 60_000)
  assert.equal((await snapshot()).pending, null, 'hidden once past the grace')
  // The server had finished the update; the next answer (here prompted by
  // the app socket reconnecting) confirms it.
  server.status = { ...READY, version: '1.1.0', serverStartedAt: 11 }
  await dropSockets(server)
  await advance(page, 2_000)
  const resumed = await snapshot()
  assert.equal(resumed.version, '1.1.0')
  assert.equal(resumed.pending?.serverFinished, true)
})

test('a reload past the grace reconciles a saved operation before discarding it', async t => {
  const { page, server, snapshot } = await fixture(t)
  await page.evaluate(() => window.serverUpdater.act('update', true))
  server.status = null
  await advance(page, 11 * 60_000)
  server.status = { ...READY, version: '1.1.0', serverStartedAt: 11 }
  await page.reload()
  await load(page)
  await page.waitForFunction(() => window.serverUpdater.snapshot().version === '1.1.0')
  assert.equal((await snapshot()).pending?.serverFinished, true)
})

test('a slow forwarded client check while minimized installs what it finds', async t => {
  const { page, server, snapshot } = await fixture(t, { desktop: true })
  await page.evaluate(() => window.serverUpdater.clientUpdaterReady())
  await page.evaluate(() => window.serverUpdater.act('update', true))
  await setAppActive(page, false)
  server.status = { ...READY, version: '1.1.0', serverStartedAt: 11 }
  await advance(page, 4_000)
  assert.equal((await snapshot()).pending?.serverFinished, true)
  assert.ok((await page.evaluate(() => window.ownerMessages)).includes('check'), 'check forwarded to the updater window')
  // The owner window is still checking five minutes later.
  await advance(page, 5 * 60_000)
  assert.equal((await snapshot()).pending?.serverFinished, true, 'intent survives a long check')
  const checks = (await page.evaluate(() => window.ownerMessages)).filter(type => type === 'check').length
  assert.equal(checks, 1, 'no duplicate checks while one is running')
  await page.evaluate(() => window.publishOwner({ isChecking: false, hasUpdate: true, availableVersion: '1.2.0', lastCheckedAt: 't1' }))
  await advance(page, 4_000)
  assert.ok((await page.evaluate(() => window.ownerMessages)).includes('download'), 'the found update is installed')
  assert.equal((await snapshot()).pending, null)
})

test('a hidden operation keeps polling while minimized and runs the client stage on recovery', async t => {
  const { page, server, snapshot } = await fixture(t, { desktop: true })
  await page.evaluate(() => window.serverUpdater.clientUpdaterReady())
  await page.evaluate(() => window.serverUpdater.act('update', true))
  await setAppActive(page, false)
  // Status requests fail past the grace window; the cached status says ready.
  server.status = null
  await advance(page, 11 * 60_000)
  assert.equal((await snapshot()).pending, null, 'hidden once past the grace')
  const hidden = server.statusRequests
  await advance(page, 30_000)
  assert.ok(server.statusRequests > hidden, 'still polling for the answer that resolves it')
  // Recovery while still minimized: the server finished the update.
  server.status = { ...READY, version: '1.1.0', serverStartedAt: 11 }
  await advance(page, 4_000)
  assert.equal((await snapshot()).pending?.serverFinished, true)
  assert.ok((await page.evaluate(() => window.ownerMessages)).includes('check'), 'client stage ran without foregrounding')
})

test('an unconfirmed operation past the grace expires on the next server answer', async t => {
  const { page, server, snapshot } = await fixture(t)
  await page.evaluate(() => window.serverUpdater.act('update'))
  await advance(page, 11 * 60_000)
  const after = await snapshot()
  assert.equal(after.pending, null)
  assert.equal(after.version, '1.0.0')
  assert.equal(after.busy, false)
  assert.equal(server.commands.length, 1)
  const quiet = server.statusRequests
  await advance(page, 5 * 60_000)
  assert.equal(server.statusRequests, quiet, 'back to idle')
})
