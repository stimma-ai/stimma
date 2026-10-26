import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/homeLoad.ts', import.meta.url)), name: 'HomeLoadTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const HOME_READS = ['/api/chats/previews', '/api/assets/browse', '/api/boards', '/api/flows', '/api/models/available']

function chat(id, name) {
  return { id, name, message_count: 1, project_id: null, updated_at: '2026-01-01T00:00:00Z' }
}

/**
 * Serve Home's API. `respond(path, query, headers)` may return a JSON body, a status
 * number, or a promise of either (to delay); undefined falls back to empty.
 */
async function openHome(t, { start = '/', respond = () => undefined } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const counts = new Map()
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    counts.set(path, (counts.get(path) || 0) + 1)
    let answer = await respond(path, url.searchParams, route.request().headers())
    if (typeof answer === 'number') return route.fulfill({ status: answer, json: { detail: 'unavailable' } }).catch(() => {})
    if (answer === undefined) {
      if (path === '/api/models/available') answer = { models: [{ slug: 'test', name: 'Test', available: true, selectable: true }], global_default: 'test', llm_configured: true }
      else if (path === '/api/chats/previews' || path === '/api/assets/browse') answer = { items: [], total: 0 }
      else answer = []
    }
    return route.fulfill({ json: answer }).catch(() => {})
  })
  await page.goto(`http://home-load.test/?start=${encodeURIComponent(start)}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return { page, counts, errors, push: path => page.evaluate(path => window.homeLoadTest.router.push(path), path) }
}

const composer = page => page.locator('.chat-input-textarea')
const recents = page => page.locator('[data-recents-state]')

test('the KeepAlive initial mount reads Home once, and a quick return reuses it', async t => {
  const { page, counts, errors, push } = await openHome(t)
  await expect(composer(page)).toBeVisible()
  await page.waitForTimeout(500)
  for (const path of HOME_READS) assert.equal(counts.get(path), 1, `${path} read once on mount`)
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')

  await push('/elsewhere')
  await expect(page.locator('#elsewhere')).toBeVisible()
  await push('/')
  await expect(composer(page)).toBeVisible()
  await page.waitForTimeout(300)
  for (const path of HOME_READS.slice(0, 4)) assert.equal(counts.get(path), 1, `${path} not reread while fresh`)
  assert.deepEqual(errors, [])
})

test('a slow recents read does not hide the composer, and neither does slow artwork', async t => {
  let releaseChats
  const chatsGate = new Promise(resolve => { releaseChats = resolve })
  const { page, errors } = await openHome(t, {
    respond: async path => {
      if (path === '/api/chats/previews') { await chatsGate; return { items: [chat(1, 'Late chat')], total: 1 } }
      if (path === '/api/boards') return [{ id: 5, name: 'Mood board', asset_count: 2, updated_at: '2025-01-01T00:00:00Z' }]
      if (path === '/api/boards/5') return new Promise(() => {})
    },
  })
  await expect(composer(page)).toBeVisible()
  await expect(composer(page)).toBeEditable()
  await expect(page.locator('main > div > div > div').first()).toHaveCSS('opacity', '1')
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'loading')
  // Boards arrived; their artwork never does. The card still shows.
  await expect(page.getByText('Mood board')).toBeVisible()
  releaseChats()
  await expect(page.getByText('Late chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  assert.deepEqual(errors, [])
})

test('a failed recents read keeps the composer usable and offers a retry', async t => {
  let fail = true
  const { page, counts } = await openHome(t, {
    respond: path => {
      if (path === '/api/chats/previews') return fail ? 503 : { items: [chat(2, 'Recovered chat')], total: 1 }
    },
  })
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'error')
  await expect(composer(page)).toBeVisible()
  await composer(page).fill('a usable composer')
  await expect(composer(page)).toHaveValue('a usable composer')
  await expect(page.getByText("Couldn't load recent chats.")).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Recovered chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  assert.equal(counts.get('/api/chats/previews'), 2)
})

test('a late response from the previous project never replaces the new one', async t => {
  let releaseFirst
  const firstGate = new Promise(resolve => { releaseFirst = resolve })
  let firstAssetsDone
  const firstAssets = new Promise(resolve => { firstAssetsDone = resolve })
  const { page, push } = await openHome(t, {
    start: '/projects/1',
    respond: async (path, query) => {
      const project = query.get('project_id')
      if (path === '/api/chats/previews') {
        if (project === '1') { await firstGate; return { items: [{ ...chat(11, 'Project one chat'), project_id: 1 }], total: 1 } }
        return { items: [{ ...chat(22, 'Project two chat'), project_id: 2 }], total: 1 }
      }
      if (path === '/api/boards') {
        if (project === '1') { await firstGate; return [{ id: 7, name: 'Project one board', asset_count: 1, project_id: 1 }] }
        return []
      }
      if (path === '/api/assets/browse' && project === '1') { await firstGate; firstAssetsDone(); return { items: [{ id: 99, media_id: 99, file_hash: 'x' }], total: 1 } }
    },
  })
  await expect(composer(page)).toBeVisible()
  await push('/projects/2')
  await expect(page.getByText('Project two chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  releaseFirst()
  await firstAssets
  await page.waitForTimeout(400)
  await expect(page.getByText('Project two chat')).toBeVisible()
  await expect(page.getByText('Project one chat')).toHaveCount(0)
  await expect(page.getByText('Project one board')).toHaveCount(0)
  await expect(page.getByText('Fresh from this project')).toHaveCount(0)
})

const homeContent = page => page.locator('main > div > div > div').first()
const hang = () => new Promise(() => {})

test('a stalled model check does not keep Home hidden', async t => {
  // Recents settle: Home shows at once, composer usable.
  const settled = await openHome(t, { respond: path => (path === '/api/models/available' ? hang() : undefined) })
  await expect(recents(settled.page)).toHaveAttribute('data-recents-state', 'ready')
  await expect(homeContent(settled.page)).toHaveCSS('opacity', '1')
  await composer(settled.page).fill('still usable')
  // Nothing settles: the bounded wait still reveals the composer.
  const stalled = await openHome(t, { respond: path => (path === '/api/models/available' || path === '/api/chats/previews' ? hang() : undefined) })
  await expect(recents(stalled.page)).toHaveAttribute('data-recents-state', 'loading')
  await expect(homeContent(stalled.page)).toHaveCSS('opacity', '1', { timeout: 4000 })
  await expect(composer(stalled.page)).toBeEditable()
})

test('a partly failed recents load keeps what loaded and names what failed', async t => {
  let fail = true
  const { page } = await openHome(t, {
    respond: path => {
      if (path === '/api/chats/previews') return fail ? 503 : { items: [chat(3, 'Chat is back')], total: 1 }
      if (path === '/api/boards') return [{ id: 5, name: 'Loaded board', asset_count: 1, updated_at: '2025-01-01T00:00:00Z' }]
    },
  })
  await expect(page.getByText('Loaded board')).toBeVisible()
  await expect(page.getByText("Couldn't load recent chats.")).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Chat is back')).toBeVisible()
  await expect(page.locator('[data-recents-error]')).toHaveCount(0)
  await expect(page.getByText('Loaded board')).toBeVisible()
})

test('server and local change events make the next visit reload', async t => {
  const { page, counts, push } = await openHome(t)
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  const reads = () => counts.get('/api/chats/previews')
  async function visitAfter(change, arg) {
    const before = reads()
    await push('/elsewhere')
    await page.evaluate(change, arg)
    await push('/')
    await expect.poll(reads).toBe(before + 1)
    await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  }
  for (const event of ['project_assets_changed', 'chat_cleared', 'chat_item_deleted', 'chat_item_updated', 'media_updated']) {
    await visitAfter(name => window.homeLoadTest.serverEvent(name, { project_id: 1 }), event)
  }
  await visitAfter(() => window.dispatchEvent(new CustomEvent('project-assets-changed', { detail: { project_id: 1, asset_ids: [1], media_ids: [], action: 'added' } })))
  // A dropped socket may have missed events; its reconnect counts as a change.
  await visitAfter(async () => {
    const sockets = window.homeLoadTest.socketCount()
    window.homeLoadTest.dropSocket()
    while (window.homeLoadTest.socketCount() === sockets) await new Promise(resolve => setTimeout(resolve, 50))
    await new Promise(resolve => setTimeout(resolve, 50))
  })
  // Without a change, a return stays on the fresh data.
  const before = reads()
  await push('/elsewhere')
  await push('/')
  await page.waitForTimeout(300)
  assert.equal(reads(), before)
})

test('a model read for one profile is never shared with or applied to another', async t => {
  let releaseA
  const gateA = new Promise(resolve => { releaseA = resolve })
  const { page } = await openHome(t, {
    start: '/elsewhere',
    respond: async (path, query, headers) => {
      if (path !== '/api/models/available') return
      const profile = headers['x-profile-id']
      if (profile === 'a') await gateA
      const name = profile === 'a' ? 'Profile A model' : 'Profile B model'
      return { models: [{ slug: `m-${profile}`, name, available: true, selectable: true }], global_default: `m-${profile}`, llm_configured: true }
    },
  })
  await expect(page.locator('#elsewhere')).toBeVisible()
  const afterB = await page.evaluate(async () => {
    const { models, setProfile } = window.homeLoadTest
    setProfile('a')
    void models.fetchModels(null)
    // Let profile A's request go out (its headers are attached asynchronously).
    await new Promise(resolve => setTimeout(resolve, 100))
    setProfile('b')
    // Joining A's read would wait on A forever; give up and report instead.
    await Promise.race([models.fetchModels(null), new Promise(resolve => setTimeout(resolve, 2000))])
    return models.models.value.map(model => model.name)
  })
  assert.deepEqual(afterB, ['Profile B model'])
  releaseA()
  await page.waitForTimeout(300)
  assert.deepEqual(await page.evaluate(() => window.homeLoadTest.models.models.value.map(model => model.name)), ['Profile B model'])
})

test('a stalled tool catalog does not hold up refreshing recents', async t => {
  const { page, counts, push } = await openHome(t, {
    respond: path => (path.startsWith('/api/tools/providers') ? hang() : undefined),
  })
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  await push('/elsewhere')
  await page.evaluate(() => window.homeLoadTest.serverEvent('chat_created', {}))
  await push('/')
  await expect.poll(() => counts.get('/api/chats/previews')).toBe(2)
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
})

test("a late tool catalog from the previous profile never replaces the new profile's tools", async t => {
  let releaseA
  const gateA = new Promise(resolve => { releaseA = resolve })
  const tool = (id, name) => ({ full_tool_id: id, tool_id: id, provider_id: 'p', name, availability: 'available' })
  const { page, push } = await openHome(t, {
    start: '/elsewhere',
    respond: async (path, query, headers) => {
      const profile = headers['x-profile-id']
      if (path === '/api/chats/previews') return { items: [chat(4, `Chat for ${profile}`)], total: 1 }
      if (!path.startsWith('/api/tools/providers')) return
      if (profile === 'a') await gateA
      if (path === '/api/tools/providers') return []
      return profile === 'a' ? [tool('p:private-a', 'Private tool A')] : [tool('p:tool-b', 'Tool B')]
    },
  })
  await expect(page.locator('#elsewhere')).toBeVisible()
  await page.evaluate(() => {
    const test = window.homeLoadTest
    // Both tools are recent in B's own history, so a leaked A catalog would show.
    test.setProfile('b')
    test.recordToolVisit('p:private-a', 'Private tool A')
    test.recordToolVisit('p:tool-b', 'Tool B')
    test.setProfile('a')
  })
  await push('/')
  await expect(page.getByText('Chat for a')).toBeVisible()
  await page.waitForTimeout(200)
  await page.evaluate(() => window.homeLoadTest.setProfile('b'))
  await expect(page.getByText('Chat for b')).toBeVisible()
  await expect(page.getByText('Tool B')).toBeVisible()
  releaseA()
  await page.waitForTimeout(400)
  await expect(page.getByText('Tool B')).toBeVisible()
  await expect(page.getByText('Private tool A')).toHaveCount(0)
})

test('a late "no chat model" answer does not take away a composer the user typed into', async t => {
  let releaseModels
  const modelsGate = new Promise(resolve => { releaseModels = resolve })
  const { page } = await openHome(t, {
    respond: async path => {
      if (path !== '/api/models/available') return
      await modelsGate
      return { models: [], global_default: 'auto', llm_configured: false }
    },
  })
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  await composer(page).fill('my draft')
  releaseModels()
  await expect(page.getByText('Stimma needs AI to work')).toBeVisible()
  await expect(page.getByText('Chat is available once you')).toHaveCount(0)
  // An untouched composer does give way to the tools hero.
  const fresh = await openHome(t, {
    respond: path => (path === '/api/models/available' ? { models: [], global_default: 'auto', llm_configured: false } : undefined),
  })
  await expect(fresh.page.getByText('Chat is available once you')).toBeVisible()
})

test('a slow recents read is waited for across repeated visits, never restarted', async t => {
  let releaseChats
  const chatsGate = new Promise(resolve => { releaseChats = resolve })
  const { page, counts, push } = await openHome(t, {
    respond: async path => {
      if (path === '/api/chats/previews') { await chatsGate; return { items: [chat(5, 'Slow but sure')], total: 1 } }
    },
  })
  await expect(composer(page)).toBeVisible()
  for (let visit = 0; visit < 3; visit++) {
    await push('/elsewhere')
    await page.evaluate(() => window.homeLoadTest.serverEvent('chat_created', {}))
    await push('/')
    await expect(composer(page)).toBeVisible()
  }
  await page.waitForTimeout(300)
  assert.equal(counts.get('/api/chats/previews'), 1)
  releaseChats()
  await expect(page.getByText('Slow but sure')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
})

test('a catalog read that predates a tool change never refills the shared cache', async t => {
  let releaseOld
  const oldGate = new Promise(resolve => { releaseOld = resolve })
  let toolReads = 0
  const tool = (id, name) => ({ full_tool_id: id, tool_id: id, provider_id: 'p', name, availability: 'available' })
  const { page, counts } = await openHome(t, {
    respond: async path => {
      if (path === '/api/tools/providers') return []
      if (path !== '/api/tools/providers/tools') return
      toolReads++
      if (toolReads === 1) { await oldGate; return [tool('p:old', 'Old tool')] }
      return [tool('p:new', 'New tool')]
    },
  })
  await expect(composer(page)).toBeVisible()
  await expect.poll(() => toolReads).toBe(1)
  // The server reports a tool change; Home rereads and the new read lands first.
  await page.evaluate(() => window.homeLoadTest.serverEvent('tools_updated', {}))
  await expect.poll(() => toolReads).toBe(2)
  await page.waitForTimeout(200)
  releaseOld()
  await page.waitForTimeout(300)
  const before = counts.get('/api/tools/providers/tools')
  const names = await page.evaluate(async () => (await window.homeLoadTest.catalog.fetchProvidersAndTools()).tools.map(item => item.name))
  assert.deepEqual(names, ['New tool'])
  assert.equal(counts.get('/api/tools/providers/tools'), before, 'served from the cache')
})
