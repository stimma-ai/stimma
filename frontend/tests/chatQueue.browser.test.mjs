import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Greet like a server without realtime scopes, which sends every event.
const welcome = ws => ws.send(JSON.stringify({ event: 'connected', data: {} }))

const instrument = { name: 'chat-queue-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.queueView = { messageQueue, messageInput, inputAttachments, agentRunning, modelsFetched, sendMessage }; defineExpose({})\n</script>')
} }
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)), plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatQueue.ts', import.meta.url)), name: 'ChatQueueTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

test('Enter steers into the running turn, Alt+Enter queues, and Stop sends what is pending', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const posts = []
  let steerStatus = 200
  let socket
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => { socket = ws; welcome(ws) })
  await page.route('**/*', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (request.method() === 'POST' && path.startsWith('/api/chats/')) posts.push({ path, body: request.postDataJSON() })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').pop()), name: 'Queue test', model_slug: 'test', generation_settings: {} } })
    if (path.endsWith('/plan-status')) return route.fulfill({ json: { has_plan: true, status: 'running' } })
    if (path.endsWith('/steer')) return route.fulfill({ status: steerStatus, json: {} })
    if (path.endsWith('/items') && request.method() === 'POST') return route.fulfill({ json: { id: 99, item_type: 'user_message', message_text: request.postDataJSON().message_text } })
    if (path.endsWith('/items')) return route.fulfill({ json: { items: [], has_more: false } })
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat-queue.test/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.queueView?.modelsFetched.value)).toBe(true)
  await expect.poll(() => page.evaluate(() => window.queueView.agentRunning.value)).toBe(true)
  await expect.poll(() => Boolean(socket)).toBe(true)

  const queue = () => page.evaluate(() => window.queueView.messageQueue.value.map(m => ({ text: m.text, mode: m.mode, steering: m.steering })))
  const steers = () => posts.filter(p => p.path === '/api/chats/1/steer')
  const itemPosts = () => posts.filter(p => p.path === '/api/chats/1/items')
  const send = (text, attachments = []) => page.evaluate(([text, attachments]) => {
    window.queueView.messageInput.value = text
    window.queueView.inputAttachments.value = attachments
    return window.queueView.sendMessage()
  }, [text, attachments])
  const textarea = page.locator('textarea.chat-input-textarea')
  const deliver = steerId => socket.send(JSON.stringify({ event: 'chat_item_created', data: { chat_id: 1, item: {
    id: Math.floor(Math.random() * 1e6), item_type: 'user_message', message_text: 'delivered', item_metadata: { steer_id: steerId },
  } } }))

  // Plain Enter while the agent runs steers straight into the turn, attachments and all.
  await send('Match the grade of these two', [{ media_id: 11 }, { media_id: 12 }])
  await expect.poll(queue).toEqual([{ text: 'Match the grade of these two', mode: 'steer', steering: true }])
  await expect.poll(() => steers().length).toBe(1)
  assert.equal(steers()[0].body.message_text, 'Match the grade of these two')
  assert.deepEqual(steers()[0].body.selected_media_ids, [11, 12])
  await expect(page.getByText('Steering')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete' })).toHaveCount(0)
  deliver(steers()[0].body.steer_id)
  await expect.poll(queue).toEqual([])

  // Alt+Enter holds a message for after the turn; its Steer button promotes it.
  await textarea.fill('then put the best one on a template')
  await textarea.press('Alt+Enter')
  await textarea.fill('square, not 16:9')
  await textarea.press('Alt+Enter')
  assert.deepEqual(await queue(), [
    { text: 'then put the best one on a template', mode: 'queue', steering: false },
    { text: 'square, not 16:9', mode: 'queue', steering: false },
  ])
  assert.equal(steers().length, 1)
  await page.getByRole('button', { name: 'Steer' }).nth(1).click()
  await expect.poll(queue).toEqual([
    { text: 'then put the best one on a template', mode: 'queue', steering: false },
    { text: 'square, not 16:9', mode: 'steer', steering: true },
  ])
  deliver(steers()[1].body.steer_id)
  await expect.poll(queue).toEqual([{ text: 'then put the best one on a template', mode: 'queue', steering: false }])

  // Edit pulls one queued message back into the composer.
  await textarea.fill('')
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect.poll(queue).toEqual([])
  assert.equal(await page.evaluate(() => window.queueView.messageInput.value), 'then put the best one on a template')

  // A steer the server refuses (its run isn't registered) is retried.
  steerStatus = 409
  await send('make it warmer')
  await expect.poll(() => steers().length).toBe(3)
  await expect.poll(queue).toEqual([{ text: 'make it warmer', mode: 'steer', steering: false }])
  steerStatus = 200
  await expect.poll(() => steers().length, { timeout: 3000 }).toBe(4)
  await expect.poll(queue).toEqual([{ text: 'make it warmer', mode: 'steer', steering: true }])

  // Stop keeps pending messages: the first starts the next turn, the rest steer into it.
  await page.evaluate(() => { window.queueView.messageInput.value = '' })
  await textarea.fill('and a square crop')
  await textarea.press('Alt+Enter')
  await send('no text overlay')
  await expect.poll(() => steers().length).toBe(5)
  await page.getByRole('button', { name: 'Stop' }).click()
  assert.ok(posts.some(p => p.path === '/api/chats/1/stop'))
  assert.equal(await page.evaluate(() => window.queueView.messageInput.value), '')
  assert.equal((await queue()).length, 3)
  socket.send(JSON.stringify({ event: 'agent_stopped', data: { chat_id: 1, reason: 'cancelled' } }))
  await expect.poll(() => itemPosts().length).toBe(1)
  assert.equal(itemPosts()[0].body.message_text, 'make it warmer')
  // The server dropped the held steer on Stop; it goes to the new turn.
  await expect.poll(() => steers().length).toBe(6)
  assert.equal(steers()[5].body.message_text, 'no text overlay')
  await expect.poll(queue).toEqual([
    { text: 'and a square crop', mode: 'queue', steering: false },
    { text: 'no text overlay', mode: 'steer', steering: true },
  ])
  deliver(steers()[5].body.steer_id)
  await expect.poll(queue).toEqual([{ text: 'and a square crop', mode: 'queue', steering: false }])

  // Leaving a chat with messages queued puts them in that chat's composer.
  await textarea.fill('keep this one')
  await textarea.press('Alt+Enter')
  assert.equal((await queue()).length, 2)
  await page.evaluate(() => window.queueTest.router.push('/chat/2'))
  await expect.poll(queue).toEqual([])
  await page.evaluate(() => window.queueTest.router.push('/chat/1'))
  await expect.poll(() => page.evaluate(() => window.queueView.messageInput.value)).toBe('and a square crop\nkeep this one')
  assert.equal(itemPosts().length, 1)
  assert.deepEqual(errors, [])
})
