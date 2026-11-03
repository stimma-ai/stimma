import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const instrument = { name: 'action-errors-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.actionView = { items, deleteFromHere, replayFromHere, modelsFetched };\n</script>')
} }
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)), plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/actionErrors.ts', import.meta.url)), name: 'ActionErrorsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t, fail) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  let failDelete
  const pendingDelete = new Promise(resolve => { failDelete = resolve })
  const posts = []
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => ws.send(JSON.stringify({ event: 'connected', data: {} })))
  await page.route('**/*', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (request.method() === 'POST') posts.push(path)
    if (path.endsWith('/delete-from-here')) {
      await pendingDelete
      return fail === 'network' ? route.abort('failed') : route.fulfill({ status: 500, json: { detail: 'Delete refused' } })
    }
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').pop()), name: 'Action test', generation_settings: {} } })
    if (path.endsWith('/plan-status')) return route.fulfill({ json: { has_plan: false } })
    if (path.endsWith('/items')) return route.fulfill({ json: { items: [], has_more: false } })
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://action-errors.test/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.actionView?.modelsFetched.value)).toBe(true)
  await page.evaluate(() => {
    window.actionView.items.value = [1, 2, 3].map(id => ({ id, item_type: 'user_message', message_text: `Message ${id}` }))
  })
  return { page, failDelete, posts }
}

for (const failure of ['http', 'network']) {
  test(`failed deleteFromHere restores messages and shows a toast (${failure})`, async t => {
    const { page, failDelete } = await fixture(t, failure)
    await page.evaluate(() => { window.deletion = window.actionView.deleteFromHere(2) })
    await expect.poll(() => page.evaluate(() => window.actionView.items.value.map(item => item.id))).toEqual([1])
    // A new item arrives while the optimistic deletion is in flight.
    await page.evaluate(() => window.actionView.items.value.push({ id: 4, item_type: 'user_message', message_text: 'New message' }))
    failDelete()
    await page.evaluate(() => window.deletion)
    await expect.poll(() => page.evaluate(() => window.actionView.items.value.map(item => item.id))).toEqual([1, 2, 3, 4])
    await expect(page.getByText('Message 2', { exact: true })).toBeVisible()
    await expect(page.getByText('Message 3', { exact: true })).toBeVisible()
    await expect(page.getByText("Couldn't delete messages.", { exact: true })).toHaveCount(1)
    await expect(page.getByText("Couldn't delete messages.", { exact: true })).toBeVisible()
  })
}

test('replay stops when deleteFromHere fails', async t => {
  const { page, failDelete, posts } = await fixture(t, 'http')
  await page.evaluate(() => { window.replay = window.actionView.replayFromHere(window.actionView.items.value[1]) })
  await expect.poll(() => posts.some(path => path.endsWith('/delete-from-here'))).toBe(true)
  failDelete()
  await page.evaluate(() => window.replay)
  assert.equal(posts.some(path => path.endsWith('/items')), false)
  await expect(page.getByText("Couldn't delete messages.", { exact: true })).toBeVisible()
})
