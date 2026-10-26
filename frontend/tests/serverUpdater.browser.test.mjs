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
async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  page.setDefaultTimeout(10000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  const server = { status: { ...READY }, statusRequests: 0, commands: [], sockets: new Set() }
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
  await page.addScriptTag({ content: script })
  await page.evaluate(() => window.serverUpdater.start())
  await advance(page, 1000)
  await page.waitForFunction(() => window.serverUpdater.snapshot().version === '1.0.0')
  return { page, server, snapshot: () => page.evaluate(() => window.serverUpdater.snapshot()) }
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

test('background and offline suspend polling; returning refreshes once', async t => {
  const { page, server } = await fixture(t)
  await page.evaluate(() => window.serverUpdater.act('restart'))
  await advance(page, 4_000)
  const before = server.statusRequests
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false })))
  await advance(page, 60_000)
  assert.equal(server.statusRequests, before, 'no polling in the background, even mid-operation')
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: true })))
  await advance(page, 100)
  assert.equal(server.statusRequests, before + 1, 'one refresh on return')

  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await advance(page, 60_000)
  assert.equal(server.statusRequests, before + 1, 'no polling while offline')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await advance(page, 100)
  assert.equal(server.statusRequests, before + 2)
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
