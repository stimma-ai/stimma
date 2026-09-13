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
