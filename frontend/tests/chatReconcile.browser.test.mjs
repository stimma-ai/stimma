import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const instrument = { name: 'chat-reconcile-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.reconcileView = { items, messageInput, sending, modelsFetched, messagesContainer, sendMessage, loadMore }; defineExpose({})\n</script>')
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
  await page.routeWebSocket(/\/ws$/, ws => { socket = ws })
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
