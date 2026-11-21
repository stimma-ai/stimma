// What a window carries across an in-place profile switch, in a real browser
// against a server stub that answers by the X-Profile-ID header.
import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium, expect } from '@playwright/test'

const built = await build({
  configFile: false, logLevel: 'error', plugins: [vue()],
  define: { 'process.env.NODE_ENV': '"test"' },
  build: { write: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/profileSwitch.ts', import.meta.url)), name: 'ProfileSwitchFixture', formats: ['iife'], fileName: 'fixture',
  } },
})
const code = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code

const BUNDLE = 'ai.stimma.stimma.test'
const A = 'profile-a'
const B = 'profile-b'

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const server = {
    profiles: [{ id: A, name: 'A' }, { id: B, name: 'B' }],
    docs: {
      [A]: [{ namespace: 'kv', key: 'tool_auto_delete_duration', value: '1h', rev: 1 }],
      [B]: [{ namespace: 'kv', key: 'tool_auto_delete_duration', value: '7d', rev: 1 }],
    },
    markers: { [A]: [{ id: 1, name: 'A marker' }], [B]: [{ id: 2, name: 'B marker' }] },
    hold: {},
  }
  const held = async name => {
    const gate = server.hold[name]
    if (gate) {
      delete server.hold[name]
      await gate
    }
  }
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const profile = request.headers()['x-profile-id']
    const json = body => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname.endsWith('/api/workspace')) return json({ docs: server.docs[profile] ?? [], closed_tabs: [], migration: { claimed: true } })
    if (url.pathname.endsWith('/api/workspace/docs')) return json({ changes: [] })
    if (url.pathname.endsWith('/api/profiles')) return json({ profiles: server.profiles })
    if (url.pathname.endsWith('/api/markers')) {
      const markers = server.markers[profile]
      await held(`markers:${profile}`)
      return json(markers)
    }
    if (url.pathname.endsWith('/api/media/markers/batch-get')) {
      await held(`batch:${profile}`)
      return json({ 10: [{ id: 1 }] })
    }
    if (url.pathname.endsWith('/api/auth/account')) {
      const reply = server.account
      await held('account')
      return route.fulfill({ status: reply.status ?? 200, contentType: 'application/json', body: JSON.stringify(reply.body) })
    }
    if (url.pathname.startsWith('/api')) return json({})
    return route.fulfill({ contentType: 'text/html', body: '<html><body></body></html>' })
  })
  await page.goto('http://profile-switch.test/')
  await page.evaluate(({ BUNDLE, A }) => {
    localStorage.setItem('stimma_bundle_id', BUNDLE)
    localStorage.setItem('stimma_sandbox', 'default')
    localStorage.setItem('profileId', A)
  }, { BUNDLE, A })
  await page.addScriptTag({ content: code })
  return { page, server }
}

/** Hold the next response named `name` until the returned function is called. */
function hold(server, name) {
  let release
  server.hold[name] = new Promise(resolve => { release = resolve })
  return () => release()
}

const activate = page => page.evaluate(() => window.t.activateWorkspace({ workspace_sync: 1 }))
const duration = page => page.evaluate(() => window.t.autoDelete.autoDeleteDuration.value)

test('the auto-delete setting follows an in-place switch, and later edits to it', async t => {
  const { page } = await fixture(t)
  await activate(page)
  await page.evaluate(() => window.t.autoDelete.reload())
  assert.equal(await duration(page), '1h')

  await page.evaluate(B => window.t.setCurrentProfileId(B), B)
  await expect.poll(() => duration(page)).toBe('7d')
  // Listeners that run on the switch see nothing of the profile left behind.
  assert.deepEqual(await page.evaluate(() => window.t.seenOnSwitch), [null])

  await page.evaluate(() => window.t.handleWorkspaceEvent({ origin: 'other', changes: [
    { namespace: 'kv', key: 'tool_auto_delete_duration', rev: 2, value: '30d' },
  ] }))
  assert.equal(await duration(page), '30d')
})

test('markers are reread on a switch, and a read for the old profile is dropped', async t => {
  const { page, server } = await fixture(t)
  await page.evaluate(() => window.t.markers.init())
  assert.deepEqual(await page.evaluate(() => window.t.markers.availableMarkers.value.map(m => m.name)), ['A marker'])

  const releaseBatch = hold(server, `batch:${A}`)
  const loading = page.evaluate(() => window.t.markers.loadMarkersForMedia([10]))
  await page.waitForTimeout(100)
  const releaseCatalog = hold(server, `markers:${A}`)
  void page.evaluate(() => window.t.markers.init())
  await page.evaluate(B => window.t.setCurrentProfileId(B), B)
  releaseBatch()
  await loading
  assert.deepEqual(await page.evaluate(() => window.t.markers.mediaMarkers.value), {})
  await expect.poll(() => page.evaluate(() => window.t.markers.availableMarkers.value.map(m => m.name))).toEqual(['B marker'])
  releaseCatalog()
  await page.waitForTimeout(100)
  assert.deepEqual(await page.evaluate(() => window.t.markers.availableMarkers.value.map(m => m.name)), ['B marker'])
})

test('a marker catalog that couldn\'t be read on a switch is read by the next init', async t => {
  const { page, server } = await fixture(t)
  await page.evaluate(() => window.t.markers.init())
  // B is locked: its catalog read fails until the PIN is entered.
  server.markers[B] = undefined
  await page.route('**/api/markers', route => route.request().headers()['x-profile-id'] === B && !server.markers[B]
    ? route.fulfill({ status: 403, body: '{}' })
    : route.fallback())
  await page.evaluate(B => window.t.setCurrentProfileId(B), B)
  await page.waitForTimeout(100)
  assert.deepEqual(await page.evaluate(() => window.t.markers.availableMarkers.value), [])
  server.markers[B] = [{ id: 2, name: 'B marker' }]
  await page.evaluate(() => window.t.markers.init())
  assert.deepEqual(await page.evaluate(() => window.t.markers.availableMarkers.value.map(m => m.name)), ['B marker'])
})

test('an account read that a push overtakes neither replaces it nor signs out', async t => {
  const { page, server } = await fixture(t)
  server.account = { body: { credits: 1 } }
  let release = hold(server, 'account')
  let read = page.evaluate(() => window.t.fetchCloudAccount())
  await page.waitForTimeout(100)
  await page.evaluate(() => window.t.applyCloudAccount({ credits: 500 }))
  release()
  await read
  assert.equal(await page.evaluate(() => window.t.getCloudUser()?.credits), 500)

  server.account = { status: 401, body: { detail: 'signed out' } }
  release = hold(server, 'account')
  read = page.evaluate(() => window.t.fetchCloudAccount())
  await page.waitForTimeout(100)
  await page.evaluate(() => window.t.applyCloudAccount({ credits: 700 }))
  release()
  await read
  assert.equal(await page.evaluate(() => window.t.getCloudUser()?.credits), 700)
})

test('a window whose profile is deleted elsewhere reloads into the fallback\'s own route', async t => {
  const { page, server } = await fixture(t)
  await page.evaluate(() => window.t.loadProfiles())
  await page.evaluate(({ BUNDLE, B }) => {
    localStorage.setItem(`stimma_${BUNDLE}_default_${B}_last_route`, '/browse')
  }, { BUNDLE, B })
  server.profiles = [{ id: B, name: 'B' }]
  const navigated = page.waitForURL('**/browse')
  await page.evaluate(() => window.t.loadProfiles())
  await navigated
  assert.equal(await page.evaluate(() => localStorage.getItem('profileId')), B)
})
