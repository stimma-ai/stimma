import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import tailwind from 'tailwindcss'
import loadConfig from 'tailwindcss/loadConfig.js'
import { chromium } from '@playwright/test'

const root = fileURLToPath(new URL('..', import.meta.url))
const entry = `${root}/tests/fixtures/pinLockPrivacy.js`
const built = await build({
  configFile: false, root, logLevel: 'silent',
  plugins: [{
    name: 'pin-privacy-fixture', enforce: 'pre',
    resolveId(id, importer) {
      if (id.endsWith('pinLockPrivacy.js')) return entry
      if (importer?.endsWith('/usePinLock.js')) {
        if (id === './useProfile') return '\0profile'
        if (id === '../apiConfig') return '\0api'
        if (id === '../utils/storageKeys') return '\0keys'
      }
    },
    load(id) {
      if (id === '\0profile') return `export const getCurrentProfileId = () => 'protected'`
      if (id === '\0api') return `export const getApiBase = () => '/api'`
      if (id === '\0keys') return `export const makeGlobalKey = () => 'pin-cache'`
      if (id === entry) return `
        import { createApp, ref, h, Teleport, nextTick } from 'vue'
        import * as pin from '../../src/composables/usePinLock.js'
        import '../../src/style.css'
        const locked = ref(false)
        window.fetch = () => new Promise(() => {}) // The server never answers.
        let focused = true
        document.hasFocus = () => focused
        window.setFocused = value => { focused = value }
        window.lockEvents = 0
        window.addEventListener('pin-auto-locked', () => { locked.value = true; lockEvents++ })
        createApp({ setup: () => () => locked.value
          ? h('div', { id: 'lock' }, 'Enter PIN')
          : [h('div', { id: 'private' }, 'Private workspace'), h(Teleport, { to: 'body' }, h('div', { id: 'media', style: 'visibility: visible; position: fixed; inset: 0; z-index: 20000' }, 'Private media'))]
        }).mount('#app')
        window.pin = pin
        window.locked = locked
        window.nextTick = nextTick
        pin.syncPinTimeouts([{ id: 'protected', has_pin: true, pin_idle_timeout_minutes: 1 }])
        pin.cachePin('protected', '1234')
        pin.startIdleTracking()
      `
    },
  }],
  define: { 'process.env.NODE_ENV': '"production"' },
  css: { postcss: { plugins: [tailwind({ ...loadConfig(`${root}/tailwind.config.js`), content: [`${root}/src/**/*.{vue,js,ts}`] })] } },
  build: { write: false, lib: { entry, formats: ['iife'], name: 'PinPrivacyTest' } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(r => r.output)
const script = output.find(item => item.type === 'chunk').code
const css = output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n').replace(/@import[^;]+;/g, '')

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html data-theme="dark"><body><div id="app"></div></body></html>' }))
  await page.goto('http://pin-privacy.test/')
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:00Z'))
  await page.addStyleTag({ content: css })
  await page.addScriptTag({ content: script })
  return page
}

const cache = page => page.evaluate(() => JSON.parse(sessionStorage.getItem('pin-cache')))

test('the exact idle deadline locks even when the policy request never answers', async t => {
  const page = await fixture(t)
  await page.clock.runFor(59_999)
  assert.equal(await page.locator('#private').count(), 1)
  await page.clock.runFor(1)
  assert.equal(await page.locator('#lock').count(), 1)
  assert.equal(await page.locator('#media').count(), 0)
  assert.deepEqual(await cache(page), {})
  assert.equal(await page.evaluate(() => lockEvents), 1)
})

for (const event of ['focus', 'mousedown', 'keydown', 'mousemove', 'touchstart', 'pageshow', 'stimma:app-active']) {
  test(`${event} after suspended timers cannot renew an expired PIN or expose a pre-lock frame`, async t => {
    const page = await fixture(t)
    // Move wall time without delivering the idle timer, as with OS sleep.
    await page.clock.setSystemTime(new Date('2026-01-01T00:01:01Z'))
    const immediate = await page.evaluate(type => {
      window.dispatchEvent(type === 'stimma:app-active' ? new CustomEvent(type, { detail: true }) : new Event(type, { cancelable: true }))
      return {
        covered: document.documentElement.hasAttribute('data-pin-privacy'),
        workspace: getComputedStyle(document.getElementById('private')).visibility,
        media: getComputedStyle(document.getElementById('media')).visibility,
        locked: locked.value,
      }
    }, event)
    assert.deepEqual(immediate, { covered: true, workspace: 'hidden', media: 'hidden', locked: true })
    assert.equal(await page.locator('#lock').count(), 1)
    assert.equal(await page.locator('#media').count(), 0)
    assert.deepEqual(await cache(page), {})
  })
}

test('an unfocused visible window remains readable and keeps the original idle deadline', async t => {
  const page = await fixture(t)
  const original = await cache(page)
  await page.clock.runFor(30_000)
  await page.evaluate(() => { setFocused(false); window.dispatchEvent(new Event('blur')) })
  assert.equal(await page.locator('#private').evaluate(el => getComputedStyle(el).visibility), 'visible')
  assert.equal(await page.locator('#media').evaluate(el => getComputedStyle(el).visibility), 'visible')
  await page.evaluate(() => window.dispatchEvent(new Event('mousemove')))
  assert.deepEqual(await cache(page), original, 'unfocused activity must not extend the deadline')
  await page.clock.runFor(30_000)
  assert.equal(await page.locator('#lock').count(), 1)
  assert.equal(await page.locator('#lock').evaluate(el => getComputedStyle(el).visibility), 'visible')
  assert.equal(await page.locator('#media').count(), 0)
})

test('initializing an unlocked profile in an unfocused window leaves it visible', async t => {
  const page = await fixture(t)
  await page.evaluate(() => {
    pin.stopIdleTracking()
    setFocused(false)
    pin.cachePin('protected', '1234')
    pin.startIdleTracking()
  })
  assert.equal(await page.locator('#media').evaluate(el => getComputedStyle(el).visibility), 'visible')
})

test('background snapshot is covered before expiry; a short return keeps the original deadline', async t => {
  const page = await fixture(t)
  const original = await cache(page)
  await page.clock.runFor(30_000)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false })))
  assert.equal(await page.locator('#media').evaluate(el => getComputedStyle(el).visibility), 'hidden')
  await page.evaluate(() => { setFocused(false); window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: true })) })
  assert.equal(await page.locator('#media').evaluate(el => getComputedStyle(el).visibility), 'visible')
  assert.deepEqual(await cache(page), original, 'focus must not count as activity')
  await page.clock.runFor(30_000)
  assert.equal(await page.locator('#lock').count(), 1)
})

test('real activity extends the deadline and repeated initialization installs no duplicate listeners', async t => {
  const page = await fixture(t)
  await page.clock.runFor(30_000)
  await page.evaluate(() => { pin.startIdleTracking(); window.dispatchEvent(new Event('keydown')) })
  await page.clock.runFor(59_999)
  assert.equal(await page.locator('#private').count(), 1)
  await page.clock.runFor(1)
  assert.equal(await page.locator('#lock').count(), 1)
  assert.equal(await page.evaluate(() => lockEvents), 1)
})

test('credentials checked by a request are expired synchronously too', async t => {
  const page = await fixture(t)
  await page.clock.setSystemTime(new Date('2026-01-01T00:01:01Z'))
  assert.equal(await page.evaluate(() => pin.getCachedPin('protected')), null)
  assert.equal(await page.locator('#lock').count(), 1)
})

test('the app gates all profile-owned global overlays on its lock state', () => {
  const app = readFileSync(`${root}/src/App.vue`, 'utf8')
  const gate = app.slice(app.indexOf('<template v-if="!isLocked && !showConnectionScreen">'), app.indexOf('  <!-- Mobile retains'))
  for (const name of ['ToastContainer', 'MediaDetailsModal', 'DirectoryPickerModal', 'FeedbackRoot', 'ReadinessPanel', 'BalanceCelebrationModal']) {
    assert.ok(gate.includes(`<${name}`), name)
  }
})

test('native suspension pre-covers the snapshot and retains it through a delayed wake', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false })))
  assert.equal(await page.locator('#media').evaluate(el => getComputedStyle(el).visibility), 'hidden')
  await page.clock.setSystemTime(new Date('2026-01-01T00:01:01Z'))
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: true })))
  assert.equal(await page.locator('#lock').count(), 1)
  assert.equal(await page.locator('#media').count(), 0)
})

test('a second suspension cancels a pending reveal', async t => {
  const page = await fixture(t)
  await page.evaluate(() => {
    window.dispatchEvent(new Event('focus'))
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false }))
  })
  assert.equal(await page.locator('#media').evaluate(el => getComputedStyle(el).visibility), 'hidden')
})

test('shortening the configured limit applies immediately without a server round trip', async t => {
  const page = await fixture(t)
  await page.clock.runFor(30_000)
  await page.evaluate(() => pin.syncPinTimeouts([{ id: 'protected', has_pin: true, pin_idle_timeout_minutes: 0.25 }]))
  assert.equal(await page.locator('#lock').count(), 1)
})
