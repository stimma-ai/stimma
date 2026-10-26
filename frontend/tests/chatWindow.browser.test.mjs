// A long chat opens with a bounded recent window and pages older history in
// on scroll. Windows end at a turn start (see the endpoint's display_limit),
// a reconnect window reaches back to loaded history so a short outage keeps
// it, and the Phase 1B gap protections still apply after a long outage.
import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect as baseExpect } from '@playwright/test'
import config from '../vite.config.js'
import { collectChatMedia } from '../src/utils/chatMedia.js'

// These tests wait on real conditions (items applied, a reconnect's resync
// landed), never on fixed delays. Applying hundreds of live items or
// reconnecting can take several seconds on a loaded CI runner, so allow far
// more than Playwright's 5 s default; a passing wait still returns at once.
const expect = baseExpect.configure({ timeout: 30_000 })
const CONDITION_TIMEOUT = 30_000

const instrument = { name: 'chat-window-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.reconcileView = { items, modelsFetched, messagesContainer, loadMore, hasMore, invokedSkillKeySet, messageInput, messageInputRef, liveChatMediaIds, openSlideshow, onSlideshowIndex, slideshowState, exitSlideshow, copyAllRawMessages, devModeRef, pagingState: () => ({ loadingMore, pageCursor, initialPositioning, observer: Boolean(loadMoreObserver.value), sentinel: Boolean(loadMoreSentinel.value) }) }; defineExpose({})\n</script>')
  if (id.endsWith('/tests/fixtures/chatReconcile.ts')) return `import { setCurrentProfileId as switchProfile } from '../../src/composables/useProfile'\nwindow.switchProfile = switchProfile\n${source}`
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
// items, extended to a turn start, below `before`, reaching `reach`. Capped
// windows end at their oldest complete turn unless the newest turn alone
// passes the cap.
const isVisible = item => item.item_type !== 'tool_result' && !(item.item_type === 'assistant_message' && !item.message_text)
function displayWindow(all, { display, before, reach, cap }) {
  const source = before ? all.filter(i => i.id < before) : all
  let out = []
  let visible = 0
  let complete = 0
  let done = false
  for (let k = source.length - 1; k >= 0 && out.length < cap; k--) {
    const item = source[k]
    out.push(item)
    if (item.parent_item_id) continue
    if (isVisible(item)) visible++
    if (item.item_type === 'user_message') {
      complete = out.length
      if (visible >= display && (reach == null || item.id <= reach)) { done = true; break }
    }
  }
  if (!done && out.length >= cap && complete) out = out.slice(0, complete)
  return { items: out, has_more: out.length > 0 && source.some(i => i.id < out.at(-1).id) }
}
const MEDIA_TYPES = new Set(['progress_display', 'media_display', 'scored_results', 'analysis_result', 'grid_generation'])
// only=prompts pages user messages; only=media returns only records that show
// media, scanning at most `scanCap` candidates and handing back a cursor.
// The server's media filter agrees with the collector (see the shared
// parity vectors in fixtures/chatMediaVectors.json).
const showsMedia = item => collectChatMedia([item]).length > 0
function subset(all, only, { before, limit }, scanCap, unfiltered = false) {
  const matches = item => only === 'prompts'
    ? !item.parent_item_id && item.item_type === 'user_message'
    : MEDIA_TYPES.has(item.item_type) || (item.item_type === 'assistant_message' && /\]\(media/.test(item.message_text || ''))
  const source = all.filter(i => matches(i) && (!before || i.id < before)).reverse()
  if (only === 'prompts') {
    const page = source.slice(0, limit)
    return { items: page, has_more: source.length > limit, next_before_id: page.at(-1)?.id ?? null }
  }
  const found = []
  let scanned = 0
  let cursor = before
  for (const item of source) {
    if (scanned >= scanCap || found.length >= limit) break
    scanned++
    cursor = item.id
    if (unfiltered || showsMedia(item)) found.push(item)
  }
  return { items: found, has_more: source.some(i => i.id < cursor), next_before_id: cursor }
}

async function openChat(t, initial, { rawCap = 300, reachCap = 1500, skills = [], initScript = null } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1000, height: 700 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => { if (/before_id=.*display_limit/.test(request.url())) page.__pagesIssued = (page.__pagesIssued || 0) + 1 })
  // `hold` holds the next display-window request until `held()` is called;
  // it answers with the server state from when it arrived.
  const server = { items: initial, requests: [], other: [], socket: null, skills, rawCap, reachCap, hold: false, held: null, holdPlain: false, heldPlain: null, mediaScanCap: 1000, mediaUnfiltered: false, holdMedia: false, heldMedia: null, holdPrompts: false, heldPrompts: null }
  // The server greets each socket; realtime scopes are ready once it has.
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => { server.sockets = (server.sockets || 0) + 1; server.socket = ws; ws.send(JSON.stringify({ event: 'connected', data: {} })) })
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app" style="height:650px;display:flex;flex-direction:column"></div></body></html>' })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: 1, name: 'Window test', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    if (path.endsWith('/invoked-skills')) {
      server.other.push('invoked-skills')
      return route.fulfill({ json: { skills: server.skills } })
    }
    if (path.endsWith('/items') && request.method() === 'GET') {
      const params = url.searchParams
      const num = key => params.has(key) ? Number(params.get(key)) : null
      const request = { display: num('display_limit'), before: num('before_id'), reach: num('reach_id'), limit: num('limit'), visible: num('visible_limit'), only: params.get('only') }
      if (request.only) {
        request.profile = route.request().headers()['x-profile-id']
        server.other.push(request)
        const json = subset(server.items, request.only, request, server.mediaScanCap, server.mediaUnfiltered)
        if (request.only === 'media' && server.holdMedia) {
          server.holdMedia = false
          await new Promise(resolve => { server.heldMedia = resolve })
        }
        if (request.only === 'prompts' && server.holdPrompts) {
          server.holdPrompts = false
          await new Promise(resolve => { server.heldPrompts = resolve })
        }
        return route.fulfill({ json })
      }
      if (!request.display) {
        // Plain pages (copying the whole transcript).
        request.profile = route.request().headers()['x-profile-id']
        server.other.push(request)
        const source = request.before ? server.items.filter(i => i.id < request.before) : server.items
        const page = source.slice(-request.limit).reverse()
        if (server.holdPlain) {
          server.holdPlain = false
          await new Promise(resolve => { server.heldPlain = resolve })
        }
        return route.fulfill({ json: { items: page, has_more: source.length > page.length } })
      }
      const json = displayWindow(server.items, { ...request, cap: request.reach == null ? server.rawCap : server.reachCap })
      const skillsNow = request.before == null ? server.skills : null
      request.returned = json.items.length
      server.requests.push(request)
      if (server.hold) {
        server.hold = false
        await new Promise(resolve => { server.held = resolve })
      }
      return route.fulfill({ json: { ...json, invoked_skills: skillsNow } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  if (initScript) await page.addInitScript(initScript)
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
    // Bounded by time rather than a count of scrolls, so a slow runner that
    // takes longer per page still gets there.
    async scrollToStart() {
      const deadline = Date.now() + CONDITION_TIMEOUT
      while (Date.now() < deadline) {
        if (!await page.evaluate(() => window.reconcileView.hasMore.value)) return
        await page.evaluate(() => { window.reconcileView.messagesContainer.value.scrollTop = 0 })
        await page.waitForTimeout(100)
      }
      const state = await page.evaluate(() => ({
        loaded: window.reconcileView.items.value.length,
        first: window.reconcileView.items.value[0]?.id,
        scrollTop: window.reconcileView.messagesContainer.value.scrollTop, ...window.reconcileView.pagingState(),
      }))
      const pages = server.requests.filter(r => r.before != null).length
      throw new Error(`history never finished paging: ${JSON.stringify(state)}, ${pages} older pages served, ${server.sockets} sockets opened, ${page.__pagesIssued || 0} older pages requested by the page`)
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

test('a capped window ends at a complete turn rather than mid-delegation', async t => {
  // Three delegated turns of 154 items: the delegate call's 150 children
  // render inside it. Two turns would pass the cap (300).
  const delegated = (first, n) => [
    { id: first, chat_id: 1, created_at: at, item_type: 'user_message', message_text: `Delegate ${n}`, item_metadata: null },
    { id: first + 1, chat_id: 1, created_at: at, item_type: 'tool_call', tool_name: 'delegate', tool_call_id: `d${n}`, tool_args: { task: 'x' }, item_metadata: null },
    ...Array.from({ length: 150 }, (_, i) => ({ id: first + 2 + i, chat_id: 1, created_at: at, item_type: 'tool_call', tool_name: 'bash', tool_call_id: `d${n}-${i}`, tool_args: { command: 'x' }, parent_item_id: first + 1, item_metadata: null })),
    { id: first + 152, chat_id: 1, created_at: at, item_type: 'tool_result', tool_call_id: `d${n}`, tool_result: { output: 'ok' }, item_metadata: null },
    { id: first + 153, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: Array.from({ length: 30 }, (_, i) => `Delegated ${n} line ${i}`).join('\n\n'), item_metadata: null },
  ]
  const all = [...delegated(1, 0), ...delegated(155, 1), ...delegated(309, 2)]
  const view = await openChat(t, all)
  const { page } = view
  assert.deepEqual(await view.ids(), range(309, 462))
  const loaded = await page.evaluate(() => window.reconcileView.items.value)
  assert.ok(loaded.every(item => !item.parent_item_id || loaded.some(other => other.id === item.parent_item_id)))
  await expect(page.locator('[data-partial-group]')).toHaveCount(0)
  await view.scrollToStart()
  assert.deepEqual(await view.ids(), range(1, 462))
  assert.deepEqual(view.errors, [])
})

test('an activity group split by the raw cap is marked and stays expanded as its older steps page in', async t => {
  // One enormous turn of 150 steps with a long answer: by itself it passes
  // the window cap (100), so only it is split.
  const all = turn(1, 0, 150)
  all.at(-1).message_text = Array.from({ length: 40 }, (_, i) => `Paragraph ${i}`).join('\n\n')
  const view = await openChat(t, all, { rawCap: 100 })
  const { page } = view
  const ids = await view.ids()
  assert.equal(ids.length, 100)
  assert.notEqual(ids[0], 1)
  // The partial group says older steps exist.
  await expect(page.locator('[data-partial-group]')).toHaveText('earlier steps not loaded')
  // Expand the partial group and read it from the top. Clicking scrolls the
  // group, and the sentinel above it, into view, so hold the older page that
  // triggers until the partial group has been counted.
  view.server.hold = true
  const group = page.locator('.activity-summary').first()
  await group.click()
  const partial = await page.locator('[data-scroll-anchor^="step:"]').count()
  assert.ok(partial > 0 && partial < 150, `partial group shows ${partial} steps`)
  view.server.hold = false
  view.server.held?.()
  await view.scrollToStart()
  assert.deepEqual(await view.ids(), all.map(i => i.id))
  // The completed group keeps its expansion though its first item changed.
  await expect(page.locator('[data-scroll-anchor^="step:"]')).toHaveCount(150)
  await expect(page.locator('.activity-summary')).toHaveCount(1)
  await expect(page.locator('[data-partial-group]')).toHaveCount(0)
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
  const skills = () => page.evaluate(() => [...window.reconcileView.invokedSkillKeySet.value])
  await expect.poll(skills).toEqual(['app-icons'])

  // A reconnect's window is held while it still lists the skill...
  const previous = view.server.socket
  view.server.hold = true
  previous.close()
  await expect.poll(() => view.server.socket !== previous && Boolean(view.server.held)).toBe(true)
  // ...then the injection, outside the loaded window, is deleted.
  view.server.items = view.server.items.filter(i => i.id !== 2)
  view.server.skills = []
  view.send('chat_item_deleted', { item_id: 2 })
  await expect.poll(skills).toEqual([])
  assert.ok(view.server.other.includes('invoked-skills'))
  // The stale window lands afterwards and does not bring the skill back.
  view.server.held()
  await expect.poll(() => view.server.requests.at(-1).returned > 0).toBe(true)
  await page.waitForTimeout(300)
  assert.deepEqual(await skills(), [])
  assert.deepEqual(view.errors, [])
})

test('arrow-up recall grows with paged history and fetches older prompts on demand', async t => {
  const view = await openChat(t, turns(75))
  const { page, server } = view
  // The window holds Questions 67..74; one older page adds 59..66.
  await page.evaluate(() => window.reconcileView.loadMore())
  await expect.poll(async () => (await view.ids())[0]).toBe(1 + 8 * 59)
  const input = () => page.evaluate(() => window.reconcileView.messageInput.value)
  const up = async () => {
    await page.evaluate(() => { const el = window.reconcileView.messageInputRef.value; el.focus(); el.setSelectionRange(0, 0) })
    await page.keyboard.press('ArrowUp')
  }
  const prompts = () => server.other.filter(r => r.only === 'prompts')
  // Newest first, through the paged-in history, without fetching.
  for (let n = 74; n >= 59; n--) {
    await up()
    assert.equal(await input(), `Question ${n}`)
  }
  assert.equal(prompts().length, 0)
  // Past the oldest loaded prompt, older ones are fetched on demand.
  await up()
  await expect.poll(input).toBe('Question 58')
  assert.equal(prompts().length, 1)
  assert.equal(prompts()[0].before, 1 + 8 * 59)
  for (let n = 57; n >= 9; n--) {
    await up()
    assert.equal(await input(), `Question ${n}`)
  }
  await up()
  await expect.poll(input).toBe('Question 8')
  for (let n = 7; n >= 0; n--) {
    await up()
    assert.equal(await input(), `Question ${n}`)
  }
  // The start of the chat: nothing more to fetch.
  await up()
  await page.waitForTimeout(200)
  assert.equal(await input(), 'Question 0')
  assert.equal(prompts().length, 2)
  assert.deepEqual(view.errors, [])
})

test('the slideshow sequence covers media older than the loaded transcript', async t => {
  // 150 turns that each show one image; the window holds the newest 14.
  const all = []
  for (let n = 0; n < 150; n++) {
    const first = 1 + 3 * n
    all.push(
      { id: first, chat_id: 1, created_at: at, item_type: 'user_message', message_text: `Draw ${n}`, item_metadata: null },
      { id: first + 1, chat_id: 1, created_at: at, item_type: 'media_display', message_text: null, item_metadata: { display_data: { rows: [{ output: { media_id: 1000 + n, status: 'completed' } }] } } },
      { id: first + 2, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: `Here is ${n}\n\nmore\n\nlines`, item_metadata: null },
    )
  }
  const view = await openChat(t, all)
  const { page, server } = view
  const media = () => page.evaluate(() => [...window.reconcileView.liveChatMediaIds.value])
  const loadedFirst = (await view.ids())[0]
  assert.equal(loadedFirst, 1 + 3 * 136)
  assert.deepEqual(await media(), range(1136, 1149))
  // Opening the slideshow pages in the 100 newest older images...
  await page.evaluate(() => window.reconcileView.openSlideshow(1149, 0))
  await expect.poll(media).toEqual(range(1036, 1149))
  const requests = () => server.other.filter(r => r.only === 'media')
  assert.equal(requests()[0].before, loadedFirst)
  // ...and browsing toward the start pages in the rest.
  await page.evaluate(() => window.reconcileView.onSlideshowIndex(3))
  await expect.poll(media).toEqual(range(1000, 1149))
  // Below the oldest image item fetched so far (turn 36's).
  assert.equal(requests()[1].before, 2 + 3 * 36)
  await page.evaluate(() => window.reconcileView.onSlideshowIndex(0))
  await page.waitForTimeout(200)
  assert.equal(requests().length, 2)
  // The transcript itself did not page.
  assert.equal((await view.ids())[0], loadedFirst)
  await page.evaluate(() => window.reconcileView.exitSlideshow())
})

test('copying raw messages copies the whole chat; dev token totals say they cover loaded history', async t => {
  const all = turns(75).map(item => item.item_type === 'assistant_message'
    ? { ...item, item_metadata: { llm_usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, model: 'test-model' } } }
    : item)
  const view = await openChat(t, all)
  const { page, server } = view
  await page.evaluate(() => { window.reconcileView.devModeRef.value = true })
  await expect(page.getByText('loaded history')).toBeVisible()

  await page.evaluate(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.copiedText = text } } })
  })
  await page.evaluate(() => window.reconcileView.copyAllRawMessages())
  const lines = (await page.evaluate(() => window.copiedText)).split('\n').map(line => JSON.parse(line).id)
  assert.deepEqual(lines, range(1, 600))
  assert.equal(server.other.filter(r => !r.only).length, 3)
  // The transcript itself did not page.
  assert.equal((await view.ids()).length, 64)

  await view.scrollToStart()
  await expect(page.getByText('loaded history')).toHaveCount(0)
  assert.deepEqual(view.errors, [])
})

test('a profile switch while copying cancels the copy instead of mixing profiles', async t => {
  const view = await openChat(t, turns(75))
  const { page, server } = view
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.copiedText = text } } })
  })
  // The first transcript page is held, then the profile changes.
  server.holdPlain = true
  const copying = page.evaluate(() => window.reconcileView.copyAllRawMessages())
  await expect.poll(() => Boolean(server.heldPlain)).toBe(true)
  await page.evaluate(() => window.switchProfile('other'))
  server.heldPlain()
  await copying
  await page.waitForTimeout(300)
  assert.equal(await page.evaluate(() => window.copiedText), undefined)
  // No page was requested under the new profile.
  const pages = server.other.filter(r => !r.only)
  assert.equal(pages.length, 1)
  assert.notEqual(pages[0].profile, 'other')
})

test('a window that starts inside an enormous delegation shows the partial run until its call pages in', async t => {
  const all = [
    { id: 1, chat_id: 1, created_at: at, item_type: 'user_message', message_text: 'Delegate it', item_metadata: null },
    { id: 2, chat_id: 1, created_at: at, item_type: 'tool_call', tool_name: 'delegate', tool_call_id: 'd', tool_args: { task: 'x' }, item_metadata: null },
    ...Array.from({ length: 350 }, (_, i) => ({ id: 3 + i, chat_id: 1, created_at: at, item_type: 'tool_call', tool_name: 'bash', tool_call_id: `d-${i}`, tool_args: { command: 'x' }, parent_item_id: 2, item_metadata: null })),
    { id: 353, chat_id: 1, created_at: at, item_type: 'tool_result', tool_call_id: 'd', tool_result: { output: 'ok' }, item_metadata: null },
    { id: 354, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: Array.from({ length: 40 }, (_, i) => `Done ${i}`).join('\n\n'), item_metadata: null },
  ]
  const view = await openChat(t, all)
  const { page } = view
  // The newest 300 items: the answer, the delegate's result and 298 steps
  // whose delegate call is older than the window.
  assert.equal((await view.ids())[0], 55)
  await expect(page.locator('[data-partial-turn]')).toContainText('298 steps · earlier steps not loaded')
  await view.scrollToStart()
  assert.deepEqual(await view.ids(), range(1, 354))
  await expect(page.locator('[data-partial-turn]')).toHaveCount(0)
  // The run now renders inside its delegate call's group.
  await expect(page.locator('.activity-summary')).toHaveCount(1)
  assert.deepEqual(view.errors, [])
})

test('slideshow paging reads past records that show no media', async t => {
  // An old image, then 120 cancelled batches that show nothing, then 14
  // turns of images that fill the window.
  const cancelled = { status: 'cancelled', preview_slots: [{ status: 'pending', media_ids: [] }] }
  const all = [
    { id: 1, chat_id: 1, created_at: at, item_type: 'user_message', message_text: 'Draw', item_metadata: null },
    { id: 2, chat_id: 1, created_at: at, item_type: 'media_display', message_text: null, item_metadata: { display_data: { rows: [{ output: { media_id: 999, status: 'completed' } }] } } },
    { id: 3, chat_id: 1, created_at: at, item_type: 'user_message', message_text: 'Batch', item_metadata: null },
    ...Array.from({ length: 120 }, (_, i) => ({ id: 4 + i, chat_id: 1, created_at: at, item_type: 'progress_display', message_text: null, item_metadata: { display_data: cancelled } })),
  ]
  for (let n = 0; n < 14; n++) {
    const first = 200 + 3 * n
    all.push(
      { id: first, chat_id: 1, created_at: at, item_type: 'user_message', message_text: `Draw ${n}`, item_metadata: null },
      { id: first + 1, chat_id: 1, created_at: at, item_type: 'media_display', message_text: null, item_metadata: { display_data: { rows: [{ output: { media_id: 1000 + n, status: 'completed' } }] } } },
      { id: first + 2, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: `Here is ${n}\n\nmore\n\nlines`, item_metadata: null },
    )
  }
  const view = await openChat(t, all)
  const { page, server } = view
  // The server bounds each media scan; here to 50 candidates.
  server.mediaScanCap = 50
  assert.equal((await view.ids())[0], 200)
  const media = () => page.evaluate(() => [...window.reconcileView.liveChatMediaIds.value])
  await page.evaluate(() => window.reconcileView.openSlideshow(1013, 0))
  await expect.poll(media).toEqual([999, ...range(1000, 1013)])
  // Two pages came back empty before the one holding the image.
  assert.equal(server.other.filter(r => r.only === 'media').length, 3)
  await page.evaluate(() => window.reconcileView.exitSlideshow())
})

// One image per turn: user, image, answer (3 visible items). Ids start at `first`.
function imageTurns(count, first, mediaFirst) {
  const all = []
  for (let n = 0; n < count; n++) {
    const id = first + 3 * n
    all.push(
      { id, chat_id: 1, created_at: at, item_type: 'user_message', message_text: `Draw ${n}`, item_metadata: null },
      { id: id + 1, chat_id: 1, created_at: at, item_type: 'media_display', message_text: null, item_metadata: { display_data: { rows: [{ output: { media_id: mediaFirst + n, status: 'completed' } }] } } },
      { id: id + 2, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: `Here is ${n}\n\nmore\n\nlines`, item_metadata: null },
    )
  }
  return all
}

test('a profile switch cancels slideshow paging instead of merging another profile\'s media', async t => {
  const view = await openChat(t, [...imageTurns(20, 1, 500), ...imageTurns(14, 200, 1000)])
  const { page, server } = view
  const media = () => page.evaluate(() => [...window.reconcileView.liveChatMediaIds.value])
  server.holdMedia = true
  await page.evaluate(() => window.reconcileView.openSlideshow(1013, 0))
  await expect.poll(() => Boolean(server.heldMedia)).toBe(true)
  await page.evaluate(() => window.switchProfile('other'))
  server.heldMedia()
  await page.waitForTimeout(300)
  assert.deepEqual(await media(), range(1000, 1013))
  const requests = server.other.filter(r => r.only === 'media')
  assert.equal(requests.length, 1)
  assert.notEqual(requests[0].profile, 'other')
})

test('slideshow paging keeps reading while pages add no usable media', async t => {
  // A server that returns records that show nothing usable (trashed
  // outputs) must not stop paging before an older image.
  const trashed = Array.from({ length: 100 }, (_, i) => ({ id: 20 + i, chat_id: 1, created_at: at, item_type: 'media_display', message_text: null, item_metadata: { display_data: { rows: [{ output: { media_id: 700 + i, status: 'trashed' } }] } } }))
  const view = await openChat(t, [...imageTurns(1, 1, 999), { id: 19, chat_id: 1, created_at: at, item_type: 'user_message', message_text: 'Batch', item_metadata: null }, ...trashed, ...imageTurns(14, 200, 1000)])
  const { page, server } = view
  server.mediaUnfiltered = true
  const media = () => page.evaluate(() => [...window.reconcileView.liveChatMediaIds.value])
  await page.evaluate(() => window.reconcileView.openSlideshow(1013, 0))
  await expect.poll(media).toEqual([999, ...range(1000, 1013)])
  assert.equal(server.other.filter(r => r.only === 'media').length, 2)
  await page.evaluate(() => window.reconcileView.exitSlideshow())
})

test('older media linked by a subagent reaches the slideshow', async t => {
  const delegated = [
    { id: 1, chat_id: 1, created_at: at, item_type: 'user_message', message_text: 'Delegate', item_metadata: null },
    { id: 2, chat_id: 1, created_at: at, item_type: 'tool_call', tool_name: 'delegate', tool_call_id: 'd', tool_args: { task: 'x' }, item_metadata: null },
    { id: 3, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: 'Made ![result](media:42)', parent_item_id: 2, item_metadata: null },
    { id: 4, chat_id: 1, created_at: at, item_type: 'tool_result', tool_call_id: 'd', tool_result: { output: 'ok' }, item_metadata: null },
    { id: 5, chat_id: 1, created_at: at, item_type: 'assistant_message', message_text: 'Done', item_metadata: null },
  ]
  const view = await openChat(t, [...delegated, ...imageTurns(14, 200, 1000)])
  const { page } = view
  assert.equal((await view.ids())[0], 200)
  const media = () => page.evaluate(() => [...window.reconcileView.liveChatMediaIds.value])
  await page.evaluate(() => window.reconcileView.openSlideshow(1013, 0))
  await expect.poll(media).toEqual([42, ...range(1000, 1013)])
  await page.evaluate(() => window.reconcileView.exitSlideshow())
})

// Recall up to the window's oldest prompt (Question 67), then press ArrowUp
// once more with the older-prompts request held.
async function recallPastWindow(view) {
  const { page, server } = view
  const up = async () => {
    await page.evaluate(() => { const el = window.reconcileView.messageInputRef.value; el.focus(); el.setSelectionRange(0, 0) })
    await page.keyboard.press('ArrowUp')
  }
  for (let n = 74; n >= 67; n--) await up()
  assert.equal(await page.evaluate(() => window.reconcileView.messageInput.value), 'Question 67')
  server.holdPrompts = true
  await up()
  await expect.poll(() => Boolean(server.heldPrompts)).toBe(true)
}

test('typing while older prompts load is not overwritten by the recall', async t => {
  const view = await openChat(t, turns(75))
  const { page, server } = view
  await recallPastWindow(view)
  await page.evaluate(() => { window.reconcileView.messageInputRef.value.setSelectionRange(11, 11) })
  await page.keyboard.type(' and more')
  assert.equal(await page.evaluate(() => window.reconcileView.messageInput.value), 'Question 67 and more')
  server.heldPrompts()
  await page.waitForTimeout(300)
  assert.equal(await page.evaluate(() => window.reconcileView.messageInput.value), 'Question 67 and more')
  assert.deepEqual(view.errors, [])
})

test('a profile switch while older prompts load cancels the recall', async t => {
  const view = await openChat(t, turns(75))
  const { page, server } = view
  await recallPastWindow(view)
  await page.evaluate(() => window.switchProfile('other'))
  const draft = await page.evaluate(() => window.reconcileView.messageInput.value)
  server.heldPrompts()
  await page.waitForTimeout(300)
  // Neither the composer nor recall takes the old profile's prompts.
  assert.equal(await page.evaluate(() => window.reconcileView.messageInput.value), draft)
  assert.notEqual(draft, 'Question 66')
  assert.equal(server.other.filter(r => r.only === 'prompts').length, 1)
})

test('paging follows the newest sentinel state when a busy page batches observer entries', async t => {
  // On a busy main thread the observer reports the sentinel leaving and
  // re-entering view in one callback. Acting on the oldest entry skipped the
  // load, and with no further change nothing retried it: paging stalled with
  // the sentinel in view.
  const view = await openChat(t, turns(75), {
    initScript: () => {
      const Native = window.IntersectionObserver
      window.IntersectionObserver = class extends Native {
        constructor(callback, options) {
          super(callback, options)
          window.__sentinelCallback = callback
        }
      }
    },
  })
  const { page, server } = view
  // Past the initial positioning, at the bottom: nothing pages yet.
  await page.waitForTimeout(300)
  const before = server.requests.filter(r => r.before != null).length
  assert.equal(before, 0)
  await page.evaluate(() => window.__sentinelCallback([{ isIntersecting: false }, { isIntersecting: true }]))
  await expect.poll(() => server.requests.filter(r => r.before != null).length).toBe(1)
  assert.deepEqual(view.errors, [])
})
