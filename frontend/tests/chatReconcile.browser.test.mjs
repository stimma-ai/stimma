import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Greet like a server without realtime scopes, which sends every event.
const welcome = ws => ws.send(JSON.stringify({ event: 'connected', data: {} }))

const instrument = { name: 'chat-reconcile-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.reconcileView = { items, messageInput, sending, modelsFetched, messagesContainer, sendMessage, loadMore, reloadAll, hasMore }; defineExpose({})\n</script>')
} }
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)), plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatReconcile.ts', import.meta.url)), name: 'ChatReconcileTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const user = (id, text = `Message ${id}`) => ({ id, chat_id: 1, created_at: '2026-01-01T00:00:00', item_type: 'user_message', message_text: text, item_metadata: null })

test('reconnect repairs changed and deleted items without moving the reader, the draft or a send in flight', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1000, height: 700 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))

  // Server truth, newest window only. Older history (ids 1..9) is reachable
  // solely by paging, as on a long chat.
  const older = Array.from({ length: 9 }, (_, i) => user(i + 1, `Older ${i + 1}\n\nline\n\nline`))
  let recent = [
    ...Array.from({ length: 30 }, (_, i) => user(i + 10, `Message ${i + 10}\n\nline\n\nline`)),
    { id: 40, chat_id: 1, created_at: '2026-01-01T00:00:00', item_type: 'assistant_message', message_text: '', item_metadata: { thinking_status: 'in_progress' } },
  ]
  let socket
  let releasePost
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => { socket = ws; welcome(ws) })
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app" style="height:650px;display:flex;flex-direction:column"></div></body></html>' })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: 1, name: 'Reconcile test', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    if (path.endsWith('/items') && request.method() === 'POST') {
      await new Promise(resolve => { releasePost = resolve })
      return route.fulfill({ json: user(41, request.postDataJSON().message_text) })
    }
    if (path.endsWith('/items')) {
      const beforeId = url.searchParams.get('before_id')
      if (beforeId) return route.fulfill({ json: { items: older.filter(i => i.id < Number(beforeId)).reverse(), has_more: false } })
      return route.fulfill({ json: { items: [...recent].reverse(), has_more: true } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat-reconcile.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.reconcileView?.modelsFetched.value)).toBe(true)
  await expect.poll(() => Boolean(socket)).toBe(true)
  const ids = () => page.evaluate(() => window.reconcileView.items.value.map(i => i.id))
  await expect.poll(async () => (await ids()).length).toBe(31)

  // Page in the older history, then park the reader mid-transcript.
  await page.evaluate(() => window.reconcileView.loadMore())
  await expect.poll(async () => (await ids())[0]).toBe(1)
  // A late web-font swap would reflow the transcript independently of the resync.
  await page.evaluate(() => document.fonts.ready)
  const anchor = page.locator('[data-item-id="25"]')
  // Offscreen items use content-visibility placeholders that take their real
  // size a frame or two after they come near the viewport; settle that first.
  await anchor.evaluate(async el => {
    const frame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    for (let i = 0; i < 20; i++) {
      el.scrollIntoView({ block: 'start' })
      const container = el.closest('.overflow-y-auto')
      const height = container.scrollHeight
      await frame()
      if (container.scrollHeight === height && Math.abs(el.getBoundingClientRect().top - container.getBoundingClientRect().top) < 1) return
    }
  })
  const topOf = () => anchor.evaluate(el => el.getBoundingClientRect().top - el.closest('.overflow-y-auto').getBoundingClientRect().top)
  const anchorTop = await topOf()
  await page.evaluate(() => { window.reconcileView.messageInput.value = 'half-written draft' })

  // While disconnected: an item above the reader is deleted, one is edited,
  // and the running assistant turn completes, all under unchanged IDs.
  socket.close()
  recent = recent.filter(i => i.id !== 15).map(i => {
    if (i.id === 20) return { ...i, message_text: 'Edited while away\n\nwith\n\nmore\n\nlines\n\nthan\n\nbefore' }
    if (i.id === 40) return { ...i, message_text: 'Finished answer', item_metadata: { thinking_status: 'completed', thinking_duration_seconds: 3 } }
    return i
  })

  await expect.poll(async () => (await ids()).includes(15)).toBe(false)
  const state = await page.evaluate(() => {
    const items = window.reconcileView.items.value
    return { last: items.at(-1), edited: items.find(i => i.id === 20).message_text, count: items.length }
  })
  assert.equal(state.last.message_text, 'Finished answer')
  assert.equal(state.last.item_metadata.thinking_status, 'completed')
  assert.match(state.edited, /^Edited while away/)
  // Older paged-in history is outside the snapshot and survives it.
  assert.equal(state.count, 39)
  assert.equal((await ids())[0], 1)
  await expect(page.locator('[data-item-id="40"]')).toContainText('Finished answer')
  // scrollTop is whole pixels while layout is fractional; without anchoring the
  // reader would jump by the height of the deleted and grown items.
  assert.ok(Math.abs(await topOf() - anchorTop) <= 2, `anchor moved from ${anchorTop} to ${await topOf()}`)
  assert.equal(await page.evaluate(() => window.reconcileView.messageInput.value), 'half-written draft')

  // A reconnect during a send: the resync still runs, the send stays in
  // flight, and the message lands once the server confirms it.
  await page.evaluate(() => { void window.reconcileView.sendMessage() })
  await expect.poll(() => Boolean(releasePost)).toBe(true)
  assert.equal(await page.evaluate(() => window.reconcileView.sending.value), true)
  const previous = socket
  recent = recent.map(i => i.id === 12 ? { ...i, message_text: 'Edited during send' } : i)
  previous.close()
  await expect.poll(() => socket !== previous).toBe(true)
  await expect.poll(() => page.evaluate(() => window.reconcileView.items.value.find(i => i.id === 12).message_text)).toBe('Edited during send')
  assert.equal(await page.evaluate(() => window.reconcileView.sending.value), true)
  releasePost()
  socket.send(JSON.stringify({ event: 'chat_item_created', data: { chat_id: 1, item: user(41, 'half-written draft') } }))
  await expect.poll(() => page.evaluate(() => window.reconcileView.sending.value)).toBe(false)
  await expect.poll(async () => (await ids()).at(-1)).toBe(41)
  assert.equal((await ids()).filter(id => id === 41).length, 1)
  assert.deepEqual(errors, [])
})

// A chat whose item list is a mutable server copy, with the ability to hold
// the next list request until the test releases it. A held request answers
// with the server state as of when it arrived, like a real snapshot.
async function openChat(t, initial, { hasMore = false, window: initialWindow = null } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1000, height: 700 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const server = { items: initial, window: initialWindow, requests: [], hold: false, held: null, socket: null }
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => { server.socket = ws; welcome(ws) })
  await page.route('**/*', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app" style="height:650px;display:flex;flex-direction:column"></div></body></html>' })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: 1, name: 'Reconcile test', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    if (path.endsWith('/items') && request.method() === 'GET') {
      // `server.window` makes the newest-window request partial, like the
      // real endpoint; before_id pages like the real pagination.
      const params = new URL(request.url()).searchParams
      const beforeId = Number(params.get('before_id')) || null
      const source = beforeId ? server.items.filter(i => i.id < beforeId) : server.items
      const size = beforeId ? Number(params.get('limit')) : server.window
      const page = size ? source.slice(-size) : source
      server.requests.push(beforeId)
      const json = { items: [...page].reverse(), has_more: size ? source.length > page.length : hasMore }
      if (server.hold) {
        server.hold = false
        await new Promise(resolve => { server.held = resolve })
      }
      return route.fulfill({ json })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat-reconcile.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.reconcileView?.modelsFetched.value)).toBe(true)
  await expect.poll(() => Boolean(server.socket)).toBe(true)
  await expect.poll(() => page.evaluate(() => window.reconcileView.items.value.length)).toBe(Math.min(initial.length, initialWindow ?? Infinity))
  return {
    page, server, errors,
    items: () => page.evaluate(() => window.reconcileView.items.value.map(i => ({ id: i.id, text: i.message_text }))),
    send: (event, data) => server.socket.send(JSON.stringify({ event, data: { chat_id: 1, ...data } })),
    // Drop the socket and hold the resync its reconnect triggers.
    async reconnectHeld() {
      const previous = server.socket
      server.hold = true
      server.held = null
      previous.close()
      await expect.poll(() => server.socket !== previous && Boolean(server.held)).toBe(true)
    },
  }
}

test('live changes during a resync win, including for items the transcript has not loaded', async t => {
  const view = await openChat(t, [user(1), user(2), user(3), user(4), user(5)])
  // While disconnected: item 2 is edited and item 6 is created.
  view.server.items = [user(1), user(2, 'Edited offline'), user(3), user(4), user(5), user(6, 'Created offline')]
  await view.reconnectHeld()
  // While the resync is in flight the socket reports changes its snapshot
  // predates: an update to never-loaded item 6, and a delete of loaded item 3
  // (whose filter re-wraps the surviving items in new reactive proxies).
  view.send('chat_item_updated', { item: user(6, 'Completed live') })
  view.send('chat_item_deleted', { item_id: 3 })
  await expect.poll(async () => (await view.items()).map(i => i.id)).toEqual([1, 2, 4, 5])
  view.server.held()
  await expect.poll(view.items).toEqual([
    { id: 1, text: 'Message 1' },
    { id: 2, text: 'Edited offline' },
    { id: 4, text: 'Message 4' },
    { id: 5, text: 'Message 5' },
    { id: 6, text: 'Completed live' },
  ])
  assert.deepEqual(view.errors, [])
})

test('a full reload invalidates a resync that is still in flight', async t => {
  const view = await openChat(t, [user(1), user(2), user(3), user(4), user(5)])
  // Item 6 is created while disconnected, so the held snapshot contains it.
  view.server.items = [user(1), user(2), user(3), user(4), user(5), user(6)]
  await view.reconnectHeld()
  // Item 6 is then deleted, and the view reloads from scratch showing 1..5.
  view.server.items = [user(1), user(2), user(3), user(4), user(5)]
  await view.page.evaluate(() => window.reconcileView.reloadAll())
  await expect.poll(async () => (await view.items()).map(i => i.id)).toEqual([1, 2, 3, 4, 5])
  // The older resync now answers with its stale snapshot (still holding 6).
  view.server.held()
  await view.page.waitForTimeout(300)
  assert.deepEqual((await view.items()).map(i => i.id), [1, 2, 3, 4, 5])
  assert.deepEqual(view.errors, [])
})

test('a snapshot far past the loaded history replaces it instead of leaving an unpageable hole', async t => {
  const view = await openChat(t, [user(1), user(2), user(3)])
  const { page } = view
  // Park the reader on the old history, away from the bottom.
  await page.evaluate(() => { window.reconcileView.messagesContainer.value.scrollTop = 0 })
  // While away the chat grows to 400 items; the endpoint returns only the
  // newest 200, so the snapshot starts at 201 and shares nothing with 1..3.
  view.server.items = Array.from({ length: 400 }, (_, i) => user(i + 1))
  view.server.window = 200
  view.server.socket.close()
  await expect.poll(async () => (await view.items())[0].id).toBe(201)
  const ids = (await view.items()).map(i => i.id)
  assert.equal(ids.length, 200)
  assert.equal(ids.at(-1), 400)
  // The reader's old messages are gone, so the view lands on the newest.
  await expect(page.locator('[data-scroll-anchor="item:400"]')).toBeInViewport()
  // Paging continues from the snapshot's start and reaches the beginning.
  view.server.requests.length = 0
  await expect.poll(() => page.evaluate(async () => {
    await window.reconcileView.loadMore()
    return window.reconcileView.items.value[0].id
  }), { timeout: 20000 }).toBe(1)
  assert.equal(view.server.requests[0], 201)
  const all = (await view.items()).map(i => i.id)
  assert.deepEqual(all, Array.from({ length: 400 }, (_, i) => i + 1))
  assert.deepEqual(view.errors, [])
})

// Page back until the transcript starts at item 1 (bounded).
async function pageToStart(page) {
  for (let i = 0; i < 20; i++) {
    const first = await page.evaluate(async () => {
      await window.reconcileView.loadMore()
      return window.reconcileView.items.value[0].id
    })
    if (first === 1) return
  }
}

test('a second reconnect before the first resync lands cannot recreate the gap', async t => {
  const view = await openChat(t, [user(1), user(2), user(3)])
  const { page } = view
  view.server.items = Array.from({ length: 400 }, (_, i) => user(i + 1))
  view.server.window = 200
  await view.reconnectHeld()
  const firstHeld = view.server.held
  // Item 400 arrives live, then the socket drops again before the first
  // resync answers. The live item must not pass for continuity with 201..400.
  view.send('chat_item_created', { item: user(400) })
  await expect.poll(async () => (await view.items()).map(i => i.id)).toEqual([1, 2, 3, 400])
  const previous = view.server.socket
  previous.close()
  await expect.poll(async () => (await view.items())[0].id).toBe(201)
  assert.equal((await view.items()).length, 200)
  assert.equal(await page.evaluate(() => window.reconcileView.hasMore.value), true)
  // The superseded first resync answers late and changes nothing.
  firstHeld()
  await page.waitForTimeout(300)
  assert.equal((await view.items())[0].id, 201)
  await pageToStart(page)
  assert.deepEqual((await view.items()).map(i => i.id), Array.from({ length: 400 }, (_, i) => i + 1))
  assert.deepEqual(view.errors, [])
})

test('a live delete of the snapshot\'s first item still enables paging', async t => {
  const view = await openChat(t, [user(1), user(2), user(3)])
  const { page } = view
  view.server.items = Array.from({ length: 400 }, (_, i) => user(i + 1))
  view.server.window = 200
  await view.reconnectHeld()
  assert.equal(await page.evaluate(() => window.reconcileView.hasMore.value), false)
  // The held snapshot still starts at 201, but 201 is deleted live.
  view.server.items = view.server.items.filter(i => i.id !== 201)
  view.send('chat_item_deleted', { item_id: 201 })
  view.server.held()
  await expect.poll(async () => (await view.items())[0].id).toBe(202)
  assert.equal(await page.evaluate(() => window.reconcileView.hasMore.value), true)
  // Paging continues below the snapshot's first id (201, now deleted; the
  // endpoint bounds by id) and reaches the beginning.
  view.server.requests.length = 0
  await pageToStart(page)
  assert.equal(view.server.requests.find(id => id !== null), 201)
  assert.deepEqual((await view.items()).map(i => i.id), Array.from({ length: 400 }, (_, i) => i + 1).filter(id => id !== 201))
  assert.deepEqual(view.errors, [])
})

test('an older page that answers after a resync replaced the boundary is discarded', async t => {
  const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i)
  const view = await openChat(t, range(1, 400).map(id => user(id)), { window: 200 })
  const { page } = view
  assert.equal((await view.items())[0].id, 201)
  // Ask for the page below 201 and hold it.
  view.server.hold = true
  view.server.held = null
  void page.evaluate(() => window.reconcileView.loadMore())
  await expect.poll(() => Boolean(view.server.held)).toBe(true)
  const heldPage = view.server.held
  // The chat grows to 800 and a reconnect replaces the transcript with 601..800.
  view.server.items = range(1, 800).map(id => user(id))
  view.server.socket.close()
  await expect.poll(async () => (await view.items())[0].id).toBe(601)
  // The page for the old boundary (151..200) answers late and is dropped.
  heldPage()
  await page.waitForTimeout(300)
  assert.equal((await view.items())[0].id, 601)
  await pageToStart(page)
  assert.deepEqual((await view.items()).map(i => i.id), range(1, 800))
  assert.deepEqual(view.errors, [])
})

test('scrolling keeps paging after a discarded page, even with an empty transcript', async t => {
  // Driven only by scrolling and the real IntersectionObserver.
  const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i)
  const view = await openChat(t, range(1, 400).map(id => user(id)), { window: 200 })
  const { page } = view
  await page.waitForTimeout(300)
  // Scroll to the top; the sentinel asks for the page below 201, held.
  view.server.hold = true
  view.server.held = null
  await page.evaluate(() => { window.reconcileView.messagesContainer.value.scrollTop = 0 })
  await expect.poll(() => Boolean(view.server.held)).toBe(true)
  const heldPage = view.server.held
  // A reconnect replaces the transcript with 601..800, then every one of
  // those is deleted live: the transcript is empty but older history exists.
  view.server.items = range(1, 800).map(id => user(id))
  view.server.socket.close()
  await expect.poll(async () => (await view.items())[0]?.id).toBe(601)
  view.server.items = range(1, 600).map(id => user(id))
  for (let id = 601; id <= 800; id++) view.send('chat_item_deleted', { item_id: id })
  await expect.poll(async () => (await view.items()).length).toBe(0)
  await expect(page.getByText('Loading older messages...')).toBeVisible()
  // The obsolete page answers and is discarded; paging must pick up again
  // from the visible sentinel without any further scrolling.
  heldPage()
  await expect.poll(async () => (await view.items()).map(i => i.id).includes(600), { timeout: 10000 }).toBe(true)
  assert.ok(!(await view.items()).some(i => i.id < 551 && i.id > 200), 'no stale page from the old boundary')
  assert.deepEqual(view.errors, [])
})

test('deleting every snapshot item still leaves older history reachable', async t => {
  const view = await openChat(t, [user(1), user(2), user(3)])
  const { page } = view
  view.server.items = Array.from({ length: 400 }, (_, i) => user(i + 1))
  view.server.window = 200
  await view.reconnectHeld()
  // Every item in the held snapshot (201..400) is deleted live.
  for (let id = 201; id <= 400; id++) view.send('chat_item_deleted', { item_id: id })
  view.server.items = view.server.items.filter(i => i.id <= 200)
  await expect.poll(async () => (await view.items()).map(i => i.id)).toEqual([1, 2, 3])
  view.server.requests.length = 0
  view.server.held()
  await expect.poll(() => page.evaluate(() => window.reconcileView.hasMore.value)).toBe(true)
  await expect(page.getByText('Loading older messages...')).toBeAttached()
  await pageToStart(page)
  assert.equal(view.server.requests.find(id => id !== null), 201)
  assert.deepEqual((await view.items()).map(i => i.id), Array.from({ length: 200 }, (_, i) => i + 1))
  assert.deepEqual(view.errors, [])
})

test('reading inside an expanded activity group stays put when steps change', async t => {
  const steps = []
  for (let n = 0; n < 60; n++) {
    const id = 10 + n * 2
    steps.push(
      { id, chat_id: 1, created_at: '2026-01-01T00:00:00', item_type: 'tool_call', tool_name: 'bash', tool_call_id: `call-${n}`, tool_args: { command: `echo step ${n}` }, item_metadata: null },
      { id: id + 1, chat_id: 1, created_at: '2026-01-01T00:00:00', item_type: 'tool_result', tool_call_id: `call-${n}`, tool_result: { output: `step ${n}` }, item_metadata: null },
    )
  }
  const answer = { id: 500, chat_id: 1, created_at: '2026-01-01T00:00:00', item_type: 'assistant_message', message_text: 'All done', item_metadata: null }
  // A long answer keeps room below the reader once later steps are removed,
  // so the scroll position is never clamped by the shorter transcript.
  const longText = text => [text, ...Array.from({ length: 40 }, (_, i) => `Paragraph ${i}`)].join('\n\n')
  const view = await openChat(t, [user(1, 'Run the steps'), ...steps, answer])
  const { page } = view
  await page.locator('.activity-summary').first().click()
  await expect(page.locator('[data-scroll-anchor^="step:"]')).toHaveCount(60)
  // Park the reader on a step in the middle of the expanded group.
  const reading = page.locator('[data-scroll-anchor="step:60"]')
  const topOf = () => reading.evaluate(el => el.getBoundingClientRect().top - el.closest('.overflow-y-auto').getBoundingClientRect().top)
  await reading.evaluate(async el => {
    const container = el.closest('.overflow-y-auto')
    for (let i = 0; i < 20; i++) {
      el.scrollIntoView({ block: 'start' })
      container.scrollTop -= 40
      const height = container.scrollHeight
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      if (container.scrollHeight === height) return
    }
  })
  const before = await topOf()
  assert.ok(before > 0 && before < 200, `reader parked at ${before}`)
  // While disconnected: steps above and all steps below are removed and the
  // answer is rewritten.
  view.server.items = [
    user(1, 'Run the steps'),
    // The first step stays: it names the group, so the group stays expanded.
    ...steps.filter(step => step.id < 12 || (step.id >= 20 && step.id < 80)),
    { ...answer, message_text: longText('All done, rewritten') },
  ]
  view.server.socket.close()
  await expect.poll(async () => (await view.items()).at(-1).text).toMatch(/^All done, rewritten/)
  await expect(page.locator('[data-scroll-anchor^="step:"]')).toHaveCount(31)
  assert.ok(Math.abs(await topOf() - before) <= 2, `reading position moved from ${before} to ${await topOf()}`)
  assert.deepEqual(view.errors, [])
})

test('reconciling 2,000 items stays cheap on a throttled CPU', async t => {
  const view = await openChat(t, [user(1)])
  const session = await view.page.context().newCDPSession(view.page)
  await session.send('Emulation.setCPUThrottlingRate', { rate: 4 })
  const timings = await view.page.evaluate(() => {
    const make = (id, text) => ({
      id, chat_id: 1, created_at: '2026-01-01T00:00:00', item_type: id % 3 ? 'tool_call' : 'assistant_message',
      message_text: text, tool_name: 'bash', tool_call_id: `call-${id}`, tool_args: { command: `echo ${id}`, cwd: '/work' },
      tool_result: { output: 'x'.repeat(400), exit_code: 0 }, tool_error: null, media_id: null, media_ids: [id, id + 1],
      grid_layout: null, parent_item_id: null, item_metadata: { status: 'completed', thinking_content: 'y'.repeat(300), duration: 1.5 },
    })
    const current = Array.from({ length: 2000 }, (_, i) => make(i + 1, `text ${i}`))
    const same = current.map(item => JSON.parse(JSON.stringify(item)))
    const edited = same.map(item => item.id === 1999 ? { ...item, message_text: 'edited' } : item)
    const before = new Set(current.map(item => item.id))
    const run = fresh => {
      const start = performance.now()
      const result = window.reconcileChatItems(current, fresh, { hasMore: false, before, journal: new Map(), coveredThrough: 2000 })
      return { ms: performance.now() - start, changed: result.changed }
    }
    run(same)
    return { unchanged: run(same), oneEdit: run(edited) }
  })
  console.log(`reconcile 2,000 items at 4x CPU throttle: unchanged ${timings.unchanged.ms.toFixed(1)} ms, one edit ${timings.oneEdit.ms.toFixed(1)} ms`)
  assert.equal(timings.unchanged.changed, false)
  assert.equal(timings.oneEdit.changed, true)
  assert.ok(timings.unchanged.ms < 250 && timings.oneEdit.ms < 250, JSON.stringify(timings))
})


// A current server: applies the connect-time scope, echoes it in the
// welcome, and acknowledges scope changes, holding acks while `holdAcks`.
async function openScopedChat(t, { holdAcks = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1000, height: 700 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const server = { urls: [], socket: null, scopes: [], holdAcks, heldAcks: [], reads: [], items: { 1: [user(1), user(2), user(3)], 2: [user(50)] } }
  server.releaseAcks = () => {
    server.holdAcks = false
    for (const ack of server.heldAcks.splice(0)) ack()
  }
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => {
    const url = new URL(ws.url())
    server.urls.push(url)
    server.socket = ws
    ws.send(JSON.stringify({ event: 'connected', data: { realtime_protocol: 1, realtime: {
      protocol: 1, profile_id: url.searchParams.get('profile'), topics: url.searchParams.getAll('topic'),
    } } }))
    ws.onMessage(message => {
      const { event, data } = JSON.parse(String(message))
      if (event !== 'realtime_scope') return
      server.scopes.push(data)
      const ack = () => ws.send(JSON.stringify({ event: 'realtime_scope_applied', data }))
      if (server.holdAcks) server.heldAcks.push(ack)
      else ack()
    })
  })
  await page.route('**/*', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app" style="height:650px;display:flex;flex-direction:column"></div></body></html>' })
    const chat = path.match(/^\/api\/chats\/(\d+)$/)
    if (chat) return route.fulfill({ json: { id: Number(chat[1]), name: 'Scoped test', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    const items = path.match(/^\/api\/chats\/(\d+)\/items$/)
    if (items && request.method() === 'GET') {
      server.reads.push(Number(items[1]))
      return route.fulfill({ json: { items: [...server.items[items[1]]].reverse(), has_more: false } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat-reconcile.test/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return {
    page, server, errors,
    reads: chatId => server.reads.filter(id => id === chatId).length,
    ids: () => page.evaluate(() => window.reconcileView.items.value.map(i => i.id)),
  }
}

test('the open chat is read only once a scoped server follows it, and a reconnect restores that', async t => {
  const { page, server, errors, reads, ids } = await openScopedChat(t, { holdAcks: true })
  // The open chat is followed; its transcript is not read until the server
  // confirms, so nothing broadcast in between can be missed.
  await expect.poll(() => server.scopes.length).toBe(1)
  assert.deepEqual(server.scopes[0].topics, ['chat:1'])
  assert.equal(server.urls[0].searchParams.get('realtime'), '1')
  await page.waitForTimeout(300)
  assert.equal(reads(1), 0)
  server.releaseAcks()
  await expect.poll(() => reads(1)).toBe(1)
  await expect.poll(ids).toEqual([1, 2, 3])

  // Detail for the open chat is applied live.
  server.socket.send(JSON.stringify({ event: 'chat_item_created', data: { chat_id: 1, item: user(4) } }))
  await expect.poll(async () => (await ids()).length).toBe(4)

  // A reconnect carries the subscription in its URL and resynchronizes at
  // once, without another scope round trip.
  server.socket.close()
  await expect.poll(() => server.urls.length).toBe(2)
  assert.deepEqual(server.urls[1].searchParams.getAll('topic'), ['chat:1'])
  await expect.poll(() => reads(1)).toBe(2)
  assert.equal(server.scopes.length, 1)
  assert.deepEqual(errors, [])
})

test('returning to a chat before its re-subscription is acknowledged waits for that acknowledgement', async t => {
  const { page, server, errors, reads, ids } = await openScopedChat(t)
  await expect.poll(ids).toEqual([1, 2, 3])
  assert.equal(reads(1), 1)

  // Leave chat 1 and come straight back while the server sits on the acks.
  // The last acknowledged scope still lists chat 1, but its unsubscribe and
  // resubscribe are in flight: reading now could miss its changes.
  server.holdAcks = true
  await page.evaluate(() => window.chatRouter.push('/chat/2'))
  await expect.poll(() => server.scopes.at(-1).topics).toEqual(['chat:2'])
  await page.evaluate(() => window.chatRouter.push('/chat/1'))
  await expect.poll(() => server.scopes.at(-1).topics).toEqual(['chat:1'])
  await page.waitForTimeout(300)
  assert.equal(reads(1), 1, 'no read of chat 1 on a stale acknowledgement')

  server.releaseAcks()
  await expect.poll(() => reads(1)).toBe(2)
  await expect.poll(ids).toEqual([1, 2, 3])
  assert.deepEqual(errors, [])
})

test('a slow acknowledgement reads provisionally, then reconciles when the server confirms', async t => {
  const { server, errors, reads, ids } = await openScopedChat(t, { holdAcks: true })
  await expect.poll(() => server.scopes.length).toBe(1)
  // The wait gives up after its bound and shows the transcript anyway.
  await expect.poll(() => reads(1), { timeout: 5000 }).toBe(1)
  await expect.poll(ids).toEqual([1, 2, 3])

  // Not yet followed, so the server sends nothing when item 4 is created.
  server.items[1] = [user(1), user(2), user(3), user(4)]
  server.releaseAcks()
  // Confirmation triggers a reconcile that picks up what was missed.
  await expect.poll(() => reads(1)).toBe(2)
  await expect.poll(ids).toEqual([1, 2, 3, 4])
  assert.deepEqual(errors, [])
})
