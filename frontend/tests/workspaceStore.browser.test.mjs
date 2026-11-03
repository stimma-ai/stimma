// The client's half of the shared workspace, in a real browser against a stub of
// the server: what it sends, what it keeps, and what it refuses to carry over.
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
    entry: fileURLToPath(new URL('./fixtures/workspaceStore.ts', import.meta.url)), name: 'WorkspaceFixture', formats: ['iife'], fileName: 'fixture',
  } },
})
const code = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code

const BUNDLE = 'ai.stimma.stimma.test'
const PROFILE = 'profile-abc123'
const P = `stimma_${BUNDLE}_default_${PROFILE}_`

async function fixture(t, { kind = null, local = {}, serverDocs = [] } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const server = { writes: [], migrations: [], reads: 0, docs: serverDocs, claimed: false, fail: false }
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    const json = body => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname.endsWith('/api/workspace')) {
      server.reads += 1
      return json({ docs: server.docs, closed_tabs: [], migration: { claimed: server.claimed } })
    }
    if (url.pathname.endsWith('/api/workspace/docs')) {
      if (server.fail) return route.abort()
      const body = route.request().postDataJSON()
      server.writes.push(body)
      return json({ changes: [] })
    }
    if (url.pathname.endsWith('/api/workspace/migrate')) {
      const body = route.request().postDataJSON()
      server.migrations.push(body)
      server.claimed = true
      server.docs = body.docs.map(doc => ({ ...doc, rev: 1 }))
      return json({ applied: true, repeat: false, stats: {} })
    }
    if (url.pathname.startsWith('/api')) return json({})
    return route.fulfill({ contentType: 'text/html', body: '<html><body></body></html>' })
  })
  await page.goto('http://workspace.test/')
  await page.evaluate(({ local, BUNDLE, PROFILE, kind }) => {
    localStorage.setItem('stimma_bundle_id', BUNDLE)
    localStorage.setItem('stimma_sandbox', 'default')
    localStorage.setItem('profileId', PROFILE)
    for (const [key, value] of Object.entries(local)) localStorage.setItem(key, value)
    if (kind === 'android') window.stimmaAndroid = { postMessage() {} }
  }, { local, BUNDLE, PROFILE, kind })
  await page.addScriptTag({ content: code })
  return { page, server }
}

const activate = (page, sync = 1) => page.evaluate(sync => window.workspace.activateWorkspace({ workspace_sync: sync }), sync)
const lastOps = server => server.writes.at(-1)?.ops

test('a server without a workspace leaves everything in local storage', async t => {
  const { page, server } = await fixture(t, { local: { [`${P}lora_show_raw`]: 'true' } })
  await activate(page, 0)
  const { read, mode, local } = await page.evaluate(P => {
    const { syncedStorage, isServerMode } = window.workspace
    syncedStorage.setItem(`${P}model_picker_recent`, '["a"]')
    return { read: syncedStorage.getItem(`${P}lora_show_raw`), mode: isServerMode(), local: localStorage.getItem(`${P}model_picker_recent`) }
  }, P)
  assert.equal(read, 'true')
  assert.equal(mode, false)
  assert.equal(local, '["a"]')
  assert.equal(server.reads, 0)
  assert.equal(server.migrations.length, 0)
})

test('writes send only what changed, and writing the same thing sends nothing', async t => {
  const { page, server } = await fixture(t, { serverDocs: [
    { namespace: 'kv', key: 'tool_x__i_1_state', value: { prompt: 'cat', steps: 4 }, rev: 3 },
  ] })
  await activate(page)
  const key = `${P}tool_x__i_1_state`
  await page.evaluate(([key]) => window.workspace.syncedStorage.setItem(key, JSON.stringify({ prompt: 'cat', steps: 4 })), [key])
  await page.waitForTimeout(400)
  assert.equal(server.writes.length, 0, 'unchanged value was sent')

  await page.evaluate(([key]) => window.workspace.syncedStorage.setItem(key, JSON.stringify({ prompt: 'dog', steps: 4 })), [key])
  await expect.poll(() => server.writes.length).toBe(1)
  assert.deepEqual(lastOps(server), [{ namespace: 'kv', key: 'tool_x__i_1_state', set: { prompt: 'dog' }, unset: [] }])
})

test('another client\'s change applies, except a field with an unsent edit here', async t => {
  const { page, server } = await fixture(t, { serverDocs: [
    { namespace: 'kv', key: 'tool_x__i_1_state', value: { prompt: 'cat', steps: 4 }, rev: 3 },
  ] })
  await activate(page)
  const result = await page.evaluate(P => {
    const { syncedStorage, handleWorkspaceEvent, getDoc } = window.workspace
    const key = `${P}tool_x__i_1_state`
    const heard = []
    syncedStorage.subscribe(key, (value, change) => heard.push(change.changedKeys))
    syncedStorage.setItem(key, JSON.stringify({ prompt: 'mine', steps: 4 }), { delayMs: 60000 })
    handleWorkspaceEvent({ origin: 'other', changes: [
      { namespace: 'kv', key: 'tool_x__i_1_state', rev: 4, set: { prompt: 'theirs', steps: 9 }, unset: [] },
    ] })
    return { doc: getDoc('kv', 'tool_x__i_1_state'), heard }
  }, P)
  assert.deepEqual(result.doc, { prompt: 'mine', steps: 9 })
  assert.deepEqual(result.heard, [['steps']])
  assert.equal(server.writes.length, 0)
})

test('this client\'s own event and a stale event are ignored', async t => {
  const { page } = await fixture(t, { serverDocs: [
    { namespace: 'kv', key: 'k', value: { a: 1 }, rev: 5 },
  ] })
  await activate(page)
  const value = await page.evaluate(() => {
    const { handleWorkspaceEvent, getDoc } = window.workspace
    handleWorkspaceEvent({ origin: 'other', changes: [{ namespace: 'kv', key: 'k', rev: 5, set: { a: 2 }, unset: [] }] })
    return getDoc('kv', 'k')
  })
  assert.deepEqual(value, { a: 1 })
})

test('changes made while the server is unreachable are kept, and survive a restart', async t => {
  const { page, server } = await fixture(t, { serverDocs: [
    { namespace: 'kv', key: 'chat_1_draft', value: { text: 'hi', attachments: [] }, rev: 2 },
  ] })
  await activate(page)
  server.fail = true
  await page.evaluate(P => window.workspace.syncedStorage.setItem(`${P}chat_1_draft`, JSON.stringify({ text: 'offline', attachments: [] })), P)
  await expect.poll(() => page.evaluate(P => localStorage.getItem(`${P}workspace_outbox`), P)).toContain('offline')

  server.fail = false
  await page.reload()
  await page.addScriptTag({ content: code })
  await activate(page)
  await expect.poll(() => server.writes.length).toBeGreaterThan(0)
  assert.deepEqual(lastOps(server)[0].set, { text: 'offline' })
  await expect.poll(() => page.evaluate(P => localStorage.getItem(`${P}workspace_outbox`), P)).toBeNull()
})

test('leaving a profile sends what\'s unsent there, and none of it follows the window', async t => {
  const { page, server } = await fixture(t, { serverDocs: [
    { namespace: 'kv', key: 'k', value: { a: 1 }, rev: 2 },
  ] })
  await activate(page)
  server.docs = [{ namespace: 'kv', key: 'k', value: { a: 100 }, rev: 9 }]
  const seenProfile = page.waitForRequest(r => r.url().endsWith('/api/workspace/docs'))
  await page.evaluate(([P]) => {
    const { syncedStorage, setCurrentProfileId } = window.workspace
    // Tool views save what's pending when told the profile is about to change.
    window.addEventListener('profile-will-change', () => {
      syncedStorage.setItem(`${P}k`, JSON.stringify({ a: 2 }), { delayMs: 60000 })
    })
    setCurrentProfileId('profile-other')
  }, [P])
  const request = await seenProfile
  assert.equal(request.headers()['x-profile-id'], PROFILE, 'sent to the profile it was made in')
  assert.deepEqual(request.postDataJSON().ops[0].set, { a: 2 })
  await activate(page)
  assert.deepEqual(await page.evaluate(() => window.workspace.getDoc('kv', 'k')), { a: 100 })
  await page.waitForTimeout(300)
  assert.equal(server.writes.length, 1)
})

test('a saved copy of what was sent doesn\'t come back after being acknowledged', async t => {
  const { page, server } = await fixture(t, { serverDocs: [{ namespace: 'kv', key: 'k', value: { a: 1 }, rev: 2 }] })
  await activate(page)
  server.fail = true
  await page.evaluate(P => window.workspace.syncedStorage.setItem(`${P}k`, JSON.stringify({ a: 2 })), P)
  await expect.poll(() => page.evaluate(P => localStorage.getItem(`${P}workspace_outbox`), P)).toContain('"a":2')
  server.fail = false
  await page.evaluate(() => window.workspace.detachProfile())
  await expect.poll(() => server.writes.length).toBe(1)
  assert.equal(await page.evaluate(P => localStorage.getItem(`${P}workspace_outbox`), P), null)
})

test('a tool state change arriving tells listeners what was held before', async t => {
  const { page } = await fixture(t, { serverDocs: [
    { namespace: 'kv', key: 'k', value: { a: 1, b: 2 }, rev: 2 },
  ] })
  await activate(page)
  const previous = await page.evaluate(P => {
    const { syncedStorage, handleWorkspaceEvent } = window.workspace
    let seen
    syncedStorage.subscribe(`${P}k`, (value, change) => { seen = change.previous })
    handleWorkspaceEvent({ origin: 'other', changes: [{ namespace: 'kv', key: 'k', rev: 3, set: { a: 9 }, unset: [] }] })
    return seen
  }, P)
  assert.deepEqual(previous, { a: 1, b: 2 })
})

const legacyStore = {
  [`${P}workspace_tabs`]: JSON.stringify([
    { id: 'tool:t:i:7', type: 'tool', entityId: 't', pinned: true, displayOrder: 0, displayName: 'T', instanceId: '7', feedScope: 't__i_7' },
    { id: 'chat:4', type: 'chat', entityId: '4', pinned: false, displayOrder: 1, displayName: 'C' },
  ]),
  [`${P}tool_t__i_7_state`]: JSON.stringify({ prompt: 'keep' }),
  [`${P}tool_t__i_7_global`]: JSON.stringify({ prompt: 'duplicate' }),
  [`${P}tool_t__i_99_state`]: JSON.stringify({ prompt: 'closed tab' }),
  [`${P}lorapool_t`]: JSON.stringify({ groups: [], ungrouped: [] }),
  [`${P}sidebar_width`]: '400',
  [`${P}last_route`]: '/browse',
  [`stimma_${BUNDLE}_default_global_pin_cache`]: '{"secret":"1234"}',
  [`stimma_${BUNDLE}_default_profile-other_workspace_tabs`]: '[{"id":"chat:9"}]',
  [`stimma_${BUNDLE}_default_profile-other_tool_t__i_7_state`]: '{"prompt":"another profile"}',
  [`stimma_ai.stimma.other_default_${PROFILE}_lorapool_t`]: '{"groups":[1]}',
}

test('a desktop uploads its workspace by the allow-list, once', async t => {
  const { page, server } = await fixture(t, { local: legacyStore })
  await activate(page)
  assert.equal(server.migrations.length, 1)
  const uploaded = Object.fromEntries(server.migrations[0].docs.map(doc => [doc.key, doc.value]))
  assert.deepEqual(Object.keys(uploaded).sort(), ['chat:4', 'lorapool_t', 'tool:t:i:7', 'tool_t__i_7_state'])
  assert.deepEqual(uploaded.tool_t__i_7_state, { prompt: 'keep' })
  assert.ok(!JSON.stringify(server.migrations[0]).includes('1234'), 'a PIN left the client')

  // Local copies stay for a downgrade; a marker stops a second upload.
  assert.ok(await page.evaluate(P => localStorage.getItem(`${P}workspace_tabs`), P))
  await page.reload()
  await page.addScriptTag({ content: code })
  await activate(page)
  assert.equal(server.migrations.length, 1)
})

test('a phone never uploads, whatever it holds', async t => {
  const { page, server } = await fixture(t, { kind: 'android', local: legacyStore })
  await activate(page)
  assert.equal(server.migrations.length, 0)
  assert.equal(await page.evaluate(() => window.workspace.isServerMode()), true)
})

test('a client with no tabs claims nothing', async t => {
  const { page, server } = await fixture(t, { local: { [`${P}lorapool_t`]: '{"groups":[]}' } })
  await activate(page)
  assert.equal(server.migrations.length, 0)
})

test('a failed upload is retried next launch', async t => {
  const { page, server } = await fixture(t, { local: legacyStore })
  await page.route('**/api/workspace/migrate', route => route.abort())
  await activate(page)
  assert.equal(await page.evaluate(P => localStorage.getItem(`${P}workspace_migrated`), P), null)
  await page.unroute('**/api/workspace/migrate')
  await activate(page)
  assert.equal(server.migrations.length, 1)
  assert.equal(await page.evaluate(P => localStorage.getItem(`${P}workspace_migrated`), P), 'claimed')
})
