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
async function openHome(t, { start = '/', respond = () => undefined, deadline = null } = {}) {
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
      // Home's compact recents read is answered only by tests that opt in;
      // everywhere else Home talks to a server that predates it.
      if (path === '/api/home/recents') return route.fulfill({ status: 404, json: { detail: 'Not Found' } }).catch(() => {})
      if (path === '/api/models/available') answer = { models: [{ slug: 'test', name: 'Test', available: true, selectable: true }], global_default: 'test', llm_configured: true }
      else if (path === '/api/chats/previews' || path === '/api/assets/browse') answer = { items: [], total: 0 }
      else answer = []
    }
    return route.fulfill({ json: answer }).catch(() => {})
  })
  await page.goto(`http://home-load.test/?start=${encodeURIComponent(start)}${deadline ? `&deadline=${deadline}` : ''}`)
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

const catalogTool = (id, name) => ({ full_tool_id: id, tool_id: id, provider_id: 'p', name, availability: 'available' })

/** Serve the tool catalog: the first read is held until released, later reads are new. */
function heldCatalog() {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const state = { reads: 0, running: 0, maxRunning: 0, release: () => release() }
  state.respond = async path => {
    if (path === '/api/chats/previews') return { items: [chat(6, 'Some chat')], total: 1 }
    if (path === '/api/tools/providers') return []
    if (path !== '/api/tools/providers/tools') return
    const read = ++state.reads
    state.running++
    state.maxRunning = Math.max(state.maxRunning, state.running)
    try {
      if (read === 1) { await gate; return [catalogTool('p:old', 'Old tool')] }
      return [catalogTool('p:new', 'New tool')]
    } finally { state.running-- }
  }
  return state
}

test('a tool change during a slow catalog read reruns once, after it, and Home ends on the new catalog', async t => {
  const catalog = heldCatalog()
  const { page, push } = await openHome(t, { respond: catalog.respond })
  await expect(composer(page)).toBeVisible()
  await page.evaluate(() => {
    window.homeLoadTest.recordToolVisit('p:old', 'Old tool')
    window.homeLoadTest.recordToolVisit('p:new', 'New tool')
  })
  await expect.poll(() => catalog.reads).toBe(1)
  // Several changes and a revisit while the first read is held: no second read yet.
  await page.evaluate(() => window.homeLoadTest.serverEvent('tools_updated', {}))
  await page.evaluate(() => window.homeLoadTest.serverEvent('tools_updated', {}))
  await push('/elsewhere')
  await push('/')
  await page.waitForTimeout(300)
  assert.equal(catalog.reads, 1)
  catalog.release()
  await expect(page.getByText('New tool')).toBeVisible()
  await expect(page.getByText('Old tool')).toHaveCount(0)
  await page.waitForTimeout(300)
  assert.equal(catalog.reads, 2, 'one coalesced rerun')
  assert.equal(catalog.maxRunning, 1)
  // Fresh now: a revisit doesn't read again.
  await push('/elsewhere')
  await push('/')
  await page.waitForTimeout(300)
  assert.equal(catalog.reads, 2)
})

test('a catalog read that predates a cache clear never refills or overrides the shared cache', async t => {
  const catalog = heldCatalog()
  const { page, counts } = await openHome(t, { respond: catalog.respond })
  await expect(composer(page)).toBeVisible()
  await expect.poll(() => catalog.reads).toBe(1)
  // Another consumer clears the cache and reads the new catalog first.
  const newer = await page.evaluate(async () => {
    window.dispatchEvent(new Event('tools-changed'))
    return (await window.homeLoadTest.catalog.fetchProvidersAndTools(true)).tools.map(item => item.name)
  })
  assert.deepEqual(newer, ['New tool'])
  catalog.release()
  await page.waitForTimeout(400)
  const before = counts.get('/api/tools/providers/tools')
  const cached = await page.evaluate(async () => (await window.homeLoadTest.catalog.fetchProvidersAndTools()).tools.map(item => item.name))
  assert.deepEqual(cached, ['New tool'])
  assert.equal(counts.get('/api/tools/providers/tools'), before, 'served from the cache')
})

for (const order of ['retry fails, rerun succeeds', 'retry succeeds, rerun fails']) {
  test(`repeated retries run one at a time and settle correctly: ${order}`, async t => {
    const firstFails = order.startsWith('retry fails')
    let reads = 0
    let running = 0
    let maxRunning = 0
    let releaseRetry
    const retryGate = new Promise(resolve => { releaseRetry = resolve })
    const { page, push } = await openHome(t, {
      respond: async path => {
        if (path !== '/api/chats/previews') return
        const read = ++reads
        running++
        maxRunning = Math.max(maxRunning, running)
        try {
          if (read === 1) return 503
          if (read === 2) { await retryGate; return firstFails ? 503 : { items: [chat(7, 'Recovered')], total: 1 } }
          if (read === 3) return firstFails ? { items: [chat(7, 'Recovered')], total: 1 } : 503
          return { items: [chat(7, 'Recovered')], total: 1 }
        } finally { running-- }
      },
    })
    await expect(page.getByText("Couldn't load recent chats.")).toBeVisible()
    const retry = page.getByRole('button', { name: 'Try again' })
    await retry.click()
    await expect.poll(() => reads).toBe(2)
    await retry.click()
    await retry.click()
    await page.waitForTimeout(300)
    assert.equal(reads, 2, 'no second read while the first retry runs')
    releaseRetry()
    await expect.poll(() => reads).toBe(3)
    await page.waitForTimeout(300)
    assert.equal(maxRunning, 1)
    await expect(page.getByText('Recovered')).toBeVisible()
    if (firstFails) {
      await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
      await expect(page.locator('[data-recents-error]')).toHaveCount(0)
      // Fresh and healthy: a revisit doesn't reread.
      await push('/elsewhere')
      await push('/')
      await page.waitForTimeout(300)
      assert.equal(reads, 3)
    } else {
      // The newer read failed: keep what loaded, offer a retry, and don't
      // treat the failure as fresh — a revisit reads again and recovers.
      await expect(page.getByText("Couldn't load recent chats.")).toBeVisible()
      await push('/elsewhere')
      await push('/')
      await expect.poll(() => reads).toBe(4)
      await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
      await expect(page.locator('[data-recents-error]')).toHaveCount(0)
    }
  })
}

test('a stalled recents read is aborted at its deadline and a retry recovers', async t => {
  let reads = 0
  const { page, counts } = await openHome(t, {
    deadline: 1500,
    respond: path => {
      if (path !== '/api/chats/previews') return
      reads++
      return reads === 1 ? hang() : { items: [chat(8, 'After the stall')], total: 1 }
    },
  })
  await expect(composer(page)).toBeVisible()
  await expect(page.getByText("Couldn't load recent chats.")).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('After the stall')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  assert.equal(counts.get('/api/chats/previews'), 2)
})

test('a stalled tool catalog read is aborted and the next visit recovers', async t => {
  let reads = 0
  const { page, push } = await openHome(t, {
    deadline: 1500,
    respond: path => {
      if (path === '/api/chats/previews') return { items: [chat(9, 'Some chat')], total: 1 }
      if (path === '/api/tools/providers') return []
      if (path !== '/api/tools/providers/tools') return
      reads++
      return reads === 1 ? hang() : [catalogTool('p:late', 'Late tool')]
    },
  })
  await expect(composer(page)).toBeVisible()
  await page.evaluate(() => window.homeLoadTest.recordToolVisit('p:late', 'Late tool'))
  await page.waitForTimeout(2000)
  await push('/elsewhere')
  await push('/')
  await expect(page.getByText('Late tool')).toBeVisible()
  assert.equal(reads, 2)
})

test('a failed forced tool refresh is not treated as fresh on the next visit', async t => {
  let reads = 0
  const { page, push } = await openHome(t, {
    respond: path => {
      if (path === '/api/chats/previews') return { items: [chat(10, 'Some chat')], total: 1 }
      if (path === '/api/tools/providers') return []
      if (path !== '/api/tools/providers/tools') return
      reads++
      if (reads === 2) return 503
      return [catalogTool('p:t', `Tool v${reads}`)]
    },
  })
  await expect(composer(page)).toBeVisible()
  await expect.poll(() => reads).toBe(1)
  await page.evaluate(() => window.homeLoadTest.serverEvent('tools_updated', {}))
  await expect.poll(() => reads).toBe(2)
  await page.waitForTimeout(200)
  await push('/elsewhere')
  await push('/')
  await expect.poll(() => reads).toBe(3)
})

for (const failing of ['/api/tools/providers', '/api/tools/providers/tools']) {
  test(`when ${failing} fails while its sibling stalls, the sibling is cancelled at once`, async t => {
    const sibling = failing === '/api/tools/providers' ? '/api/tools/providers/tools' : '/api/tools/providers'
    const reads = new Map()
    const { page, push } = await openHome(t, {
      // Far longer than the test waits: cancellation must not depend on it.
      deadline: 60_000,
      respond: path => {
        if (path === '/api/chats/previews') return { items: [chat(11, 'Some chat')], total: 1 }
        if (path !== failing && path !== sibling) return
        const read = (reads.get(path) || 0) + 1
        reads.set(path, read)
        if (read > 1) return path.endsWith('/tools') ? [catalogTool('p:ok', 'Recovered tool')] : []
        return path === failing ? 503 : hang()
      },
    })
    // Requests start before this listener exists; cancellations come later.
    let siblingCancelled = 0
    page.on('requestfailed', request => {
      if (new URL(request.url()).pathname === sibling) siblingCancelled++
    })
    await expect(composer(page)).toBeVisible()
    await page.evaluate(() => window.homeLoadTest.recordToolVisit('p:ok', 'Recovered tool'))
    await expect.poll(() => reads.get(failing) || 0).toBe(1)
    // The stalled sibling is cancelled as soon as its partner fails.
    await expect.poll(() => siblingCancelled, { timeout: 3000 }).toBe(1)
    // So a revisit starts a fresh catalog read with nothing left behind, and recovers.
    await push('/elsewhere')
    await push('/')
    await expect(page.getByText('Recovered tool')).toBeVisible()
    assert.equal(reads.get(sibling), 2)
    assert.equal(siblingCancelled, 1)
  })
}

// ==================== Compact recents ====================

const thumbnailPaths = counts => [...counts.keys()].filter(path => path.includes('/thumbnail'))
const boardReads = counts => [...counts.keys()].filter(path => path.startsWith('/api/boards'))
const flowReads = counts => [...counts.keys()].filter(path => path.startsWith('/api/flows/'))

function compactRecents({ project = null, tag = '' } = {}) {
  return {
    items: [
      { type: 'chat', chat: { ...chat(31, `Compact chat${tag}`), project_id: project, updated_at: '2026-03-03T00:00:00', recent_media: [{ media_id: 301, file_hash: 'chathash' }], last_message: 'hi' } },
      { type: 'flow', flow: { id: 41, name: `Compact flow${tag}`, project_id: project, execution_state: 'idle', pending_task_count: 0, root_status_summary: { completed: 2 }, has_load_error: false, updated_at: '2026-03-02T00:00:00', preview_media: [{ media_id: 401, file_hash: 'flowhash1' }, { media_id: 402, file_hash: 'flowhash2' }] } },
      { type: 'board', board: { id: 51, name: `Compact board${tag}`, project_id: project, asset_count: 5000, updated_at: '2026-03-01T00:00:00', preview_items: [
        { id: 501, asset_id: 501, media_id: 601, file_hash: 'boardhash1', file_format: 'png', width: 100, height: 100 },
        { id: 502, asset_id: 502, media_id: 602, file_hash: 'boardhash2', file_format: 'png', width: 200, height: 100 },
      ] } },
    ],
    has_entities: true,
  }
}

test('Home reads its cards in one compact read, with no board or flow detail reads', async t => {
  const { page, counts, errors, push } = await openHome(t, {
    respond: (path, query) => {
      if (path === '/api/home/recents') {
        assert.equal(query.get('project_id'), 'none')
        assert.equal(query.get('limit'), '3')
        return compactRecents()
      }
    },
  })
  await expect(page.getByText('Compact board')).toBeVisible()
  await expect(page.getByText('Compact flow')).toBeVisible()
  await expect(page.getByText('Compact chat')).toBeVisible()
  await expect(page.getByText(/5000 items/)).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  // Artwork comes from the compact read, by content hash.
  await expect.poll(() => thumbnailPaths(counts).filter(path => /boardhash|flowhash|chathash/.test(path)).length).toBe(5)
  assert.equal(counts.get('/api/home/recents'), 1)
  assert.deepEqual(boardReads(counts), [])
  assert.deepEqual(flowReads(counts), [])
  assert.equal(counts.get('/api/chats/previews'), undefined)
  assert.equal(counts.get('/api/assets/browse'), 1)

  await push('/elsewhere')
  await push('/')
  await page.waitForTimeout(300)
  assert.equal(counts.get('/api/home/recents'), 1, 'not reread while fresh')
  assert.deepEqual(errors, [])
})

test('compact recents: change events make the next visit reload, and a scope switch drops late replies', async t => {
  let releaseFirst
  const firstGate = new Promise(resolve => { releaseFirst = resolve })
  let firstDone
  const firstSettled = new Promise(resolve => { firstDone = resolve })
  let firstProjectReads = 0
  const { page, counts, push } = await openHome(t, {
    start: '/projects/1',
    respond: async (path, query) => {
      if (path !== '/api/home/recents') return
      const project = Number(query.get('project_id'))
      if (project === 1 && ++firstProjectReads === 1) {
        await firstGate
        firstDone()
      }
      return compactRecents({ project, tag: project === 1 ? ' one' : ' two' })
    },
  })
  await expect(composer(page)).toBeVisible()
  await push('/projects/2')
  await expect(page.getByText('Compact board two')).toBeVisible()
  releaseFirst()
  await firstSettled
  await page.waitForTimeout(300)
  await expect(page.getByText('Compact board two')).toBeVisible()
  await expect(page.getByText('Compact board one')).toHaveCount(0)

  const reads = () => counts.get('/api/home/recents')
  for (const event of ['board_items_changed', 'flow_equation_updated', 'chat_item_created']) {
    const before = reads()
    await push('/elsewhere')
    await page.evaluate(name => window.homeLoadTest.serverEvent(name, {}), event)
    await push('/projects/2')
    await expect.poll(reads).toBe(before + 1)
    await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  }
  assert.deepEqual(boardReads(counts), [])
  assert.deepEqual(flowReads(counts), [])
})

test('compact recents: a failed read keeps the composer usable and a retry recovers', async t => {
  let fail = true
  const { page, counts } = await openHome(t, {
    respond: path => {
      if (path === '/api/home/recents') return fail ? 503 : compactRecents()
    },
  })
  await expect(page.getByText("Couldn't load recent chats, boards and flows.")).toBeVisible()
  await composer(page).fill('still typing')
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Compact board')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  await expect(composer(page)).toHaveValue('still typing')
  assert.equal(counts.get('/api/home/recents'), 2)
  // A server error is not an old server: no fallback to the full lists.
  assert.equal(counts.get('/api/chats/previews'), undefined)
  assert.deepEqual(boardReads(counts), [])
})

test('compact recents: a malformed reply is a load failure, not an old server', async t => {
  let malformed = true
  const { page, counts } = await openHome(t, {
    respond: path => {
      if (path === '/api/home/recents') return malformed ? { unexpected: true } : compactRecents()
    },
  })
  await expect(page.getByText("Couldn't load recent chats, boards and flows.")).toBeVisible()
  assert.equal(counts.get('/api/chats/previews'), undefined)
  assert.deepEqual(boardReads(counts), [])
  malformed = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Compact board')).toBeVisible()
  assert.equal(counts.get('/api/home/recents'), 2)
})

test('compact recents: a stalled read is aborted at its deadline and a retry recovers', async t => {
  let reads = 0
  const { page } = await openHome(t, {
    deadline: 1500,
    respond: path => {
      if (path !== '/api/home/recents') return
      reads++
      return reads === 1 ? hang() : compactRecents()
    },
  })
  await expect(composer(page)).toBeVisible()
  await expect(page.getByText("Couldn't load recent chats, boards and flows.")).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Compact board')).toBeVisible()
  assert.equal(reads, 2)
})

test('an old server gets the full lists, each board and flow read once per load, and is asked again after a reconnect', async t => {
  const { page, counts, push } = await openHome(t, {
    respond: path => {
      if (path === '/api/chats/previews') return { items: [{ ...chat(61, 'Legacy chat'), updated_at: '2026-02-03T00:00:00Z' }], total: 1 }
      if (path === '/api/boards') return [
        { id: 5, name: 'Legacy board', asset_count: 1, updated_at: '2026-02-02T00:00:00Z' },
        { id: 6, name: 'Other board', asset_count: 1, updated_at: '2025-12-01T00:00:00Z' },
      ]
      if (path === '/api/boards/5' || path === '/api/boards/6') return { id: Number(path.split('/').pop()), sections: [{ items: [{ id: 1, media_id: 1, file_hash: 'legacyhash', width: 1, height: 1 }] }] }
      if (path === '/api/flows') return [{ id: 7, name: 'Legacy flow', updated_at: '2026-01-15T00:00:00Z' }]
    },
  })
  await expect(page.getByText('Legacy board')).toBeVisible()
  await expect(page.getByText('Legacy flow')).toBeVisible()
  await expect(page.getByText('Legacy chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  await page.waitForTimeout(300)
  const once = { '/api/home/recents': 1, '/api/chats/previews': 1, '/api/boards': 1, '/api/boards/5': 1, '/api/boards/6': 1, '/api/flows/7/equations': 1 }
  for (const [path, count] of Object.entries(once)) assert.equal(counts.get(path), count, `${path} once`)

  // The next load goes straight to the lists, still one detail read each.
  await push('/elsewhere')
  await page.evaluate(() => window.homeLoadTest.serverEvent('board_items_changed', {}))
  await push('/')
  await expect.poll(() => counts.get('/api/chats/previews')).toBe(2)
  await page.waitForTimeout(300)
  assert.equal(counts.get('/api/home/recents'), 1, 'not asked again')
  assert.equal(counts.get('/api/boards/5'), 2)
  assert.equal(counts.get('/api/boards/6'), 2)
  assert.equal(counts.get('/api/flows/7/equations'), 2)

  // The server may have been updated while the connection was down.
  await push('/elsewhere')
  await page.evaluate(async () => {
    const sockets = window.homeLoadTest.socketCount()
    window.homeLoadTest.dropSocket()
    while (window.homeLoadTest.socketCount() === sockets) await new Promise(resolve => setTimeout(resolve, 50))
    await new Promise(resolve => setTimeout(resolve, 50))
  })
  await push('/')
  await expect.poll(() => counts.get('/api/home/recents')).toBe(2)
})

