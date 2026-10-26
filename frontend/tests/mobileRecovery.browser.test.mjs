import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build, createServer } from 'vite'
import { chromium } from '@playwright/test'
import { mobileDevReconnect } from '../plugins/mobileDevReconnect.js'

const root = fileURLToPath(new URL('..', import.meta.url))
const built = await build({ configFile: false, root, logLevel: 'silent', define: { 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: `${root}/tests/fixtures/mobileRecovery.js`, formats: ['iife'], name: 'Recovery' } } })
const script = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code

test('real fetch and Axios hold unsent writes, preserve abort, and expire without replay', async t => {
  const browser = await chromium.launch(); t.after(() => browser.close())
  const page = await browser.newPage()
  const sent = []
  await page.route('http://recovery.test/**', route => {
    if (route.request().url().includes('/api/')) sent.push(route.request().url())
    return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
  })
  await page.goto('http://recovery.test/')
  await page.evaluate(() => {
    window.webkit = { messageHandlers: { stimma: { postMessage: async () => ({ connectionState: 'connecting' }) } } }
  })
  await page.addScriptTag({ content: script })
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false }))
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: true }))
    window.results = []
    fetch('/api/first', { method: 'POST', body: 'once' }).then(() => results.push('fetch'))
    recovery.axios.post('/api/second', 'once').then(() => results.push('axios'))
    const c = new AbortController()
    fetch('/api/aborted', { signal: c.signal }).catch(e => results.push(e.name))
    c.abort()
  })
  await page.waitForTimeout(150)
  assert.deepEqual(sent, [])
  assert.equal(await page.evaluate(() => recovery.visible.value), false)
  await page.evaluate(() => {
    window.dispatchEvent(new Event('stimma:transport-resumed'))
    recovery.setMobileSocketReady(true)
  })
  await page.waitForFunction(() => results.length === 3)
  assert.equal(sent.length, 2)
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('stimma:connection-state', { detail: 'connecting' }))
    window.expired = fetch('/api/expired', { method: 'POST' }).then(() => 'sent', e => e.message)
  })
  await page.waitForFunction(() => recovery.visible.value)
  assert.match(await page.evaluate(() => expired), /Still reconnecting/)
  await page.evaluate(() => window.dispatchEvent(new Event('stimma:transport-resumed')))
  assert.equal(sent.length, 2)
})

test('native recovery phases hold writes for their budgets, send them once, and never ask for sign-in', async t => {
  const browser = await chromium.launch(); t.after(() => browser.close())
  const page = await browser.newPage()
  const sent = []
  await page.route('http://recovery.test/**', route => {
    const url = route.request().url()
    if (!url.includes('/api/')) return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    sent.push(`${route.request().method()} ${new URL(url).pathname}`)
    // A device session the server's gate refused: the shell renews it, the account is still signed in.
    if (url.endsWith('/api/auth/account')) return route.fulfill({ status: 401, headers: { 'X-Stimma-Session-Invalid': '1' }, contentType: 'application/json', body: '{"detail":"Multi-device session required"}' })
    return route.fulfill({ contentType: 'application/json', body: '{}' })
  })
  await page.goto('http://recovery.test/')
  await page.evaluate(() => {
    window.nativeState = { connectionState: 'ready', recovery: { generation: 1, phase: 'ready', budgetMs: 0 } }
    window.webkit = { messageHandlers: { stimma: { postMessage: async () => window.nativeState } } }
  })
  await page.addScriptTag({ content: script })
  const native = (generation, phase, budgetMs = 0) => page.evaluate(([generation, phase, budgetMs]) => {
    window.nativeState = { connectionState: phase === 'ready' ? 'ready' : 'connecting', recovery: { generation, phase, budgetMs } }
    window.dispatchEvent(new CustomEvent('stimma:transport-state', { detail: window.nativeState.recovery }))
  }, [generation, phase, budgetMs])
  await page.evaluate(() => {
    window.authPrompts = 0
    window.addEventListener('stimma-auth-required', () => authPrompts++)
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false }))
  })
  // Backgrounded: the shell marks the path suspect; on return it checks, then re-establishes the session.
  await native(2, 'checking', 5000)
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: true }))
    window.results = []
    fetch('/api/chats/1/items', { method: 'POST', body: 'once' }).then(() => results.push('fetch'), e => results.push(e.message))
    recovery.axios.post('/api/generate', 'once').then(() => results.push('axios'), e => results.push(e.message))
  })
  await page.waitForTimeout(2600)
  assert.deepEqual(sent, [], 'held past the old two-second window because native recovery said it may take five')
  assert.equal(await page.evaluate(() => recovery.status.value), 'reconnecting')
  await native(2, 'reconnecting', 20000)
  await page.waitForTimeout(300)
  assert.deepEqual(sent, [])
  await native(2, 'ready')
  await page.evaluate(() => recovery.setMobileSocketReady(true))
  await page.waitForFunction(() => results.length === 2)
  assert.deepEqual((await page.evaluate(() => results)).sort(), ['axios', 'fetch'])
  assert.deepEqual(sent.sort(), ['POST /api/chats/1/items', 'POST /api/generate'], 'each write sent exactly once')
  assert.equal(await page.evaluate(() => recovery.visible.value), false)
  // An expired device session read during recovery is not a signed-out account.
  assert.equal(await page.evaluate(() => recovery.fetchCloudAccount().then(account => account)), null)
  assert.equal(await page.evaluate(() => authPrompts), 0)
  // Leaving the page while a write is held rejects it unsent; held reads still go out.
  await native(4, 'checking', 5000)
  await page.evaluate(async () => {
    window.navResults = []
    fetch('/api/chats/7/items', { method: 'POST', body: 'hello' }).then(() => navResults.push('post sent'), e => navResults.push(e.message))
    recovery.axios.delete('/api/boards/3').then(() => navResults.push('delete sent'), e => navResults.push(e.message))
    fetch('/api/settings').then(() => navResults.push('read'), e => navResults.push(e.message))
    // The user then taps elsewhere; the router reports a new page (router/index.js afterEach).
    await new Promise(resolve => setTimeout(resolve, 50))
    recovery.pageChanged()
  })
  await page.waitForFunction(() => navResults.length === 2)
  for (const result of await page.evaluate(() => navResults)) assert.match(result, /page changed/)
  await native(4, 'ready')
  await page.waitForFunction(() => navResults.length === 3)
  await page.waitForTimeout(200)
  assert.equal(sent.filter(entry => entry === 'POST /api/chats/7/items' || entry === 'DELETE /api/boards/3').length, 0, 'no write is dispatched after navigation')
  assert.equal(sent.filter(entry => entry === 'GET /api/settings').length, 1)
  // A long outage: unavailable fails new writes at once, shows it, and sends nothing later.
  await native(5, "checking", 5000)
  await native(5, "reconnecting", 20000)
  await native(5, "unavailable")
  assert.match(await page.evaluate(() => fetch('/api/boards', { method: 'POST' }).then(() => 'sent', e => e.message)), /Still reconnecting/)
  assert.equal(await page.evaluate(() => recovery.status.value), 'unavailable')
  await native(5, "ready")
  await page.waitForTimeout(200)
  assert.equal(sent.filter(entry => entry === 'POST /api/boards').length, 0, 'a failed write is never replayed')
  assert.equal(await page.evaluate(() => recovery.visible.value), false)
})

test('the installed Vite client reconnects without reloading an unchanged phone page', async t => {
  const server = await createServer({ configFile: false, root, logLevel: 'silent', plugins: [mobileDevReconnect()], server: { port: 0, host: '127.0.0.1' } })
  await server.listen(); t.after(() => server.close())
  const browser = await chromium.launch(); t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    window.webkit = { messageHandlers: { stimma: {} } }
    window.pageIdentity = Math.random()
    window.sockets = []
    const Original = window.WebSocket
    window.WebSocket = class extends Original { constructor(...args) { super(...args); window.sockets.push(this) } }
  })
  const origin = server.resolvedUrls.local[0]
  await page.route('**/recovery-fixture', route => route.fulfill({ contentType: 'text/html', body: '<input id="draft"><script type="module" src="/@vite/client"></script>' }))
  await page.goto(`${origin}recovery-fixture`)
  await page.waitForFunction(() => sockets.some(s => s.protocol === 'vite-hmr' && s.readyState === 1))
  const identity = await page.evaluate(() => pageIdentity)
  await page.locator('#draft').fill('Keep my place')
  for (let i = 0; i < 2; i++) {
    await page.evaluate(() => sockets.findLast(s => s.protocol === 'vite-hmr').close())
    await page.waitForFunction(() => sockets.filter(s => s.protocol === 'vite-hmr').length >= 2 && sockets.findLast(s => s.protocol === 'vite-hmr').readyState === 1)
    await page.waitForTimeout(200)
    assert.equal(await page.evaluate(() => pageIdentity), identity)
    assert.equal(await page.locator('#draft').inputValue(), 'Keep my place')
  }
  assert.deepEqual(errors, [])
  // A changed server revision means updates were missed: a reload is required.
  server.watcher.emit('all', 'change', 'fixture-change')
  await page.evaluate(() => sockets.findLast(s => s.protocol === 'vite-hmr').close())
  await page.waitForFunction(previous => pageIdentity !== previous, identity)
})
