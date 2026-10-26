// A long chat opens with a bounded recent window and pages older history in
// on scroll. Windows end at a turn start (see the endpoint's display_limit),
// a reconnect window reaches back to loaded history so a short outage keeps
// it, and the Phase 1B gap protections still apply after a long outage.
import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const instrument = { name: 'chat-window-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.reconcileView = { items, modelsFetched, messagesContainer, loadMore, hasMore, invokedSkillKeySet }; defineExpose({})\n</script>')
} }
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)), plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatReconcile.ts', import.meta.url)), name: 'ChatWindowTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const at = '2026-01-01T00:00:00'
// One agent turn: a question, an activity group of `steps` tool calls (each
// with its hidden result), and an answer. Visible items: steps + 2.
function turn(firstId, n, steps = 3) {
  const items = [{ id: firstId, chat_id: 1, created_at: at, item_type: 'user_message', message_text: `Question ${n}`, item_metadata: null }]
  let id = firstId + 1
  for (let s = 0; s < steps; s++) {
    const call = `call-${n}-${s}`
    items.push({ id: id++, chat_id: 1, created_at: at, item_type: 'tool_call', tool_name: 'bash', tool_call_id: call, tool_args: { command: `echo ${n}.${s}` }, item_metadata: null })
    items.push({ id: id++, chat_id: 1, created_at: at, item_type: 'tool_result', tool_call_id: call, tool_result: { output: 'ok' }, item_metadata: null })
  }
  items.push({ id: id++, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: `Answer ${n}\n\nwith\n\nsome\n\nlines`, item_metadata: null })
  return items
}
function turns(count, steps = 3, firstId = 1) {
  const items = []
  for (let n = 0; n < count; n++) items.push(...turn(items.length ? items.at(-1).id + 1 : firstId, n, steps))
  return items
}

// The endpoint's display window, newest first: `display` visible top-level
// items, extended to a turn start, below `before`, reaching `reach`, capped.
const isVisible = item => item.item_type !== 'tool_result' && !(item.item_type === 'assistant_message' && !item.message_text)
function displayWindow(all, { display, before, reach, cap }) {
  const source = before ? all.filter(i => i.id < before) : all
  const out = []
  let visible = 0
  for (let k = source.length - 1; k >= 0 && out.length < cap; k--) {
    const item = source[k]
    out.push(item)
    if (item.parent_item_id) continue
    if (isVisible(item)) visible++
    if (visible >= display && item.item_type === 'user_message' && (reach == null || item.id <= reach)) break
  }
  return { items: out, has_more: out.length > 0 && source.some(i => i.id < out.at(-1).id) }
}

async function openChat(t, initial, { rawCap = 300, reachCap = 1500, skills = [] } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1000, height: 700 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const server = { items: initial, requests: [], socket: null, skills, rawCap, reachCap }
  await page.routeWebSocket(/\/ws$/, ws => { server.socket = ws })
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app" style="height:650px;display:flex;flex-direction:column"></div></body></html>' })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: 1, name: 'Window test', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    if (path.endsWith('/items') && request.method() === 'GET') {
      const params = url.searchParams
      const num = key => params.has(key) ? Number(params.get(key)) : null
      const request = { display: num('display_limit'), before: num('before_id'), reach: num('reach_id'), limit: num('limit'), visible: num('visible_limit') }
      assert.ok(request.display, `every transcript request is a display window: ${url.search}`)
      const json = displayWindow(server.items, { ...request, cap: request.reach == null ? server.rawCap : server.reachCap })
      request.returned = json.items.length
      server.requests.push(request)
      return route.fulfill({ json: { ...json, invoked_skills: server.skills } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat-window.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.reconcileView?.modelsFetched.value)).toBe(true)
  await expect.poll(() => Boolean(server.socket)).toBe(true)
  await expect.poll(() => page.evaluate(() => window.reconcileView.items.value.length)).toBeGreaterThan(0)
  return {
    page, server, errors,
    ids: () => page.evaluate(() => window.reconcileView.items.value.map(i => i.id)),
    send: (event, data) => server.socket.send(JSON.stringify({ event, data: { chat_id: 1, ...data } })),
    // Scroll to the top until the whole history is loaded, as a reader would.
    async scrollToStart() {
      for (let i = 0; i < 60; i++) {
        if (!await page.evaluate(() => window.reconcileView.hasMore.value)) return
        await page.evaluate(() => { window.reconcileView.messagesContainer.value.scrollTop = 0 })
        await page.waitForTimeout(100)
      }
      throw new Error('history never finished paging')
    },
  }
}

const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i)

test('a long chat opens on a bounded window at the bottom and pages older turns whole', async t => {
  // 600 items: 75 turns of 8 items (5 visible each).
  const all = turns(75)
  assert.equal(all.length, 600)
  const view = await openChat(t, all)
  const { page, server } = view
  await page.waitForTimeout(500)

  // One request at open, a bounded window, and no older page while the
  // reader sits at the bottom.
  assert.equal(server.requests.length, 1)
  assert.equal(server.requests[0].display, 40)
  assert.equal(server.requests[0].visible, 500, 'older servers still get the legacy window')
  const opened = await view.ids()
  assert.equal(opened.length, 64)
  assert.deepEqual(opened, range(537, 600))
  await expect(page.locator('[data-scroll-anchor="item:600"]')).toBeInViewport()
  assert.equal(await page.locator('.activity-summary').count(), 8)

  // Scrolling up pages older history in turn-aligned windows.
  await view.scrollToStart()
  assert.deepEqual(await view.ids(), range(1, 600))
  assert.ok(server.requests.slice(1).every(r => r.before != null && r.display === 40))
  // Every turn's activity group is whole: one group of three steps each.
  assert.equal(await page.locator('.activity-summary').count(), 75)
  await page.locator('.activity-summary').first().click()
  await expect(page.locator('[data-scroll-anchor^="step:"]')).toHaveCount(3)
  assert.deepEqual(view.errors, [])
})

test('an activity group split by the raw cap stays expanded as its older steps page in', async t => {
  // One enormous turn of 150 steps, then a short one with a long answer.
  // The window cap (100) splits the big turn's group.
  const all = [...turn(1, 0, 150), ...turn(400, 1, 1)]
  all.at(-1).message_text = Array.from({ length: 40 }, (_, i) => `Paragraph ${i}`).join('\n\n')
  const view = await openChat(t, all, { rawCap: 100 })
  const { page } = view
  const ids = await view.ids()
  assert.equal(ids.length, 100)
  assert.notEqual(ids[0], 1)
  // Expand the partial group and read it from the top.
  const group = page.locator('.activity-summary').first()
  await group.click()
  const partial = await page.locator('[data-scroll-anchor^="step:"]').count()
  assert.ok(partial > 0 && partial < 150, `partial group shows ${partial} steps`)
  await view.scrollToStart()
  assert.deepEqual(await view.ids(), all.map(i => i.id))
  // The completed group keeps its expansion though its first item changed.
  await expect(page.locator('[data-scroll-anchor^="step:"]')).toHaveCount(150)
  await expect(page.locator('.activity-summary')).toHaveCount(2)
  // And it still collapses.
  await page.locator('.activity-summary').first().click()
  await expect(page.locator('[data-scroll-anchor^="step:"]')).toHaveCount(0)
  assert.deepEqual(view.errors, [])
})

test('a reconnect after a short outage keeps loaded history, even after a long live session', async t => {
  const view = await openChat(t, turns(75))
  const { page, server } = view
  await view.scrollToStart()
  assert.equal((await view.ids()).length, 600)

  // A long live session: 30 more turns arrive over the socket, more than a
  // plain recent window holds. Live appends do not extend covered history.
  const live = turns(30, 3, 601)
  server.items = [...server.items, ...live]
  for (const item of live) view.send('chat_item_created', { item })
  await expect.poll(async () => (await view.ids()).length).toBe(840)
  // A short outage: one item changes and one arrives while disconnected.
  const away = turn(841, 99, 1)
  server.items = server.items.map(i => i.id === 700 ? { ...i, tool_args: { command: 'edited while away' } } : i).concat(away)
  server.requests.length = 0
  server.socket.close()
  await expect.poll(async () => (await view.ids()).at(-1)).toBe(away.at(-1).id)

  // The resync reached back to the history it already held, so nothing was
  // dropped and the change inside the window was repaired.
  assert.equal(server.requests.length, 1)
  assert.equal(server.requests[0].reach, 600)
  assert.ok(server.requests[0].returned < 300, `resync returned ${server.requests[0].returned} items`)
  assert.deepEqual(await view.ids(), server.items.map(i => i.id))
  assert.equal(await page.evaluate(() => window.reconcileView.items.value.find(i => i.id === 700).tool_args.command), 'edited while away')
  assert.equal(await page.evaluate(() => window.reconcileView.hasMore.value), false)

  // Coverage now runs through the resync, so the next one reaches only that far.
  server.requests.length = 0
  server.socket.close()
  await expect.poll(() => server.requests.length).toBe(1)
  assert.equal(server.requests[0].reach, away.at(-1).id)
  assert.deepEqual(view.errors, [])
})

test('after a long outage the window cannot reach loaded history and replaces it without a hole', async t => {
  const view = await openChat(t, turns(6), { reachCap: 200 })
  const { page, server } = view
  assert.equal(await page.evaluate(() => window.reconcileView.hasMore.value), false)
  const loaded = await view.ids()
  // While away the chat grows by 600 items, past the reach cap.
  server.items = [...server.items, ...turns(75, 3, 49)]
  server.socket.close()
  await expect.poll(async () => (await view.ids()).at(-1)).toBe(648)
  const ids = await view.ids()
  assert.equal(ids.length, 200)
  assert.ok(!ids.includes(loaded.at(-1)), 'the stale run is replaced, not kept behind a gap')
  assert.equal(await page.evaluate(() => window.reconcileView.hasMore.value), true)
  await view.scrollToStart()
  assert.deepEqual(await view.ids(), range(1, 648))
  assert.deepEqual(view.errors, [])
})

test('skills invoked before the window stay active', async t => {
  const all = [
    { id: 1, chat_id: 1, created_at: at, item_type: 'user_message', message_text: 'use the skill', item_metadata: null },
    { id: 2, chat_id: 1, created_at: at, item_type: 'stimpack_injection', message_text: 'skill body', item_metadata: { skill_name: 'app-icons' } },
    ...turns(40, 3, 3),
  ]
  const view = await openChat(t, all, { skills: ['app-icons'] })
  const { page } = view
  assert.ok(!(await view.ids()).includes(2))
  await expect.poll(() => page.evaluate(() => [...window.reconcileView.invokedSkillKeySet.value])).toEqual(['app-icons'])
  assert.deepEqual(view.errors, [])
})
