import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

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

test('queued messages steer into the running turn, and Stop puts them back in the composer', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const posts = []
  let steerStatus = 200
  let socket
  await page.routeWebSocket(/\/ws$/, ws => { socket = ws })
  await page.route('**/*', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (request.method() === 'POST' && path.startsWith('/api/chats/')) posts.push({ path, body: request.postDataJSON() })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').pop()), name: 'Queue test', model_slug: 'test', generation_settings: {} } })
    if (path.endsWith('/plan-status')) return route.fulfill({ json: { has_plan: true, status: 'running' } })
    if (path.endsWith('/steer')) return route.fulfill({ status: steerStatus, json: {} })
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

  const queue = () => page.evaluate(() => window.queueView.messageQueue.value.map(m => ({ text: m.text, steering: m.steering })))
  const send = (text, attachments = []) => page.evaluate(([text, attachments]) => {
    window.queueView.messageInput.value = text
    window.queueView.inputAttachments.value = attachments
    return window.queueView.sendMessage()
  }, [text, attachments])

  // While the agent runs, sending queues.
  await send('square, not 16:9')
  await send('Match the grade of these two', [{ media_id: 11 }, { media_id: 12 }])
  await send('then put the best one on a template')
  assert.deepEqual(await queue(), [
    { text: 'square, not 16:9', steering: false },
    { text: 'Match the grade of these two', steering: false },
    { text: 'then put the best one on a template', steering: false },
  ])
  assert.equal(posts.filter(p => p.path.endsWith('/items')).length, 0)

  // Steer sends the message (with its attachments) to the running turn.
  await page.getByRole('button', { name: 'Steer' }).nth(1).click()
  await expect.poll(queue).toEqual([
    { text: 'square, not 16:9', steering: false },
    { text: 'Match the grade of these two', steering: true },
    { text: 'then put the best one on a template', steering: false },
  ])
  const steer = posts.find(p => p.path === '/api/chats/1/steer')
  assert.equal(steer.body.message_text, 'Match the grade of these two')
  assert.deepEqual(steer.body.selected_media_ids, [11, 12])
  await expect(page.getByText('Steering')).toBeVisible()

  // Delivery: the server broadcasts it as a user message carrying the steer id.
  socket.send(JSON.stringify({ event: 'chat_item_created', data: { chat_id: 1, item: {
    id: 50, item_type: 'user_message', message_text: 'Match the grade of these two',
    item_metadata: { steer_id: steer.body.steer_id, attachments: [{ media_id: 11 }, { media_id: 12 }] },
  } } }))
  await expect.poll(queue).toEqual([
    { text: 'square, not 16:9', steering: false },
    { text: 'then put the best one on a template', steering: false },
  ])

  // A steer that arrives after the run ended (409) stays queued as normal.
  steerStatus = 409
  await page.getByRole('button', { name: 'Steer' }).first().click()
  await expect.poll(() => posts.filter(p => p.path.endsWith('/steer')).length).toBe(2)
  await expect.poll(queue).toEqual([
    { text: 'square, not 16:9', steering: false },
    { text: 'then put the best one on a template', steering: false },
  ])

  // Stop puts the queue back in the composer and sends nothing.
  await send('', [{ media_id: 13 }])
  await page.getByRole('button', { name: 'Stop' }).click()
  await expect.poll(queue).toEqual([])
  assert.equal(await page.evaluate(() => window.queueView.messageInput.value), 'square, not 16:9\nthen put the best one on a template')
  assert.deepEqual(await page.evaluate(() => window.queueView.inputAttachments.value.map(a => a.media_id)), [13])
  socket.send(JSON.stringify({ event: 'agent_stopped', data: { chat_id: 1, reason: 'cancelled' } }))
  await page.waitForTimeout(200)
  assert.equal(posts.filter(p => p.path.endsWith('/items')).length, 0)
  assert.ok(posts.some(p => p.path === '/api/chats/1/stop'))

  // Leaving a chat with messages queued puts them in that chat's composer.
  await page.evaluate(() => { window.queueView.messageInput.value = ''; window.queueView.agentRunning.value = true })
  await send('keep this one')
  assert.equal((await queue()).length, 1)
  await page.evaluate(() => window.queueTest.router.push('/chat/2'))
  await expect.poll(queue).toEqual([])
  await page.evaluate(() => window.queueTest.router.push('/chat/1'))
  await expect.poll(() => page.evaluate(() => window.queueView.messageInput.value)).toBe('keep this one')
  assert.equal(posts.filter(p => p.path.endsWith('/items')).length, 0)
  assert.deepEqual(errors, [])
})
