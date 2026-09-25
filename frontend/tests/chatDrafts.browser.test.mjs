import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const instrument = { name: 'chat-drafts-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'window.chatDraftView = { composerDraft, inputAttachments, messageInput, modelsFetched, sendMessage }; defineExpose({})\n</script>')
} }
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)), plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatDrafts.ts', import.meta.url)), name: 'ChatDraftsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

test('chat drafts survive navigation, repeated drops, reload and failed sends', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let rejectSend = false
  let releaseSend
  let releaseUpload
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (/^\/api\/chats\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').pop()), name: 'Draft test', model_slug: 'test', generation_settings: {} } })
    if (path === '/api/generate/upload-reference') {
      await new Promise(resolve => { releaseUpload = resolve })
      return route.fulfill({ json: { media_id: 31, filename: 'upload.png' } })
    }
    if (path.endsWith('/items')) {
      if (route.request().method() === 'POST' && rejectSend) {
        await new Promise(resolve => { releaseSend = resolve })
        return route.fulfill({ status: 500, json: {} })
      }
      return route.fulfill({ json: { items: [], has_more: false } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  async function boot() {
    await page.goto('http://chat-drafts.test/')
    await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
    await expect.poll(() => page.evaluate(() => window.chatDraftView?.modelsFetched.value)).toBe(true)
  }
  const state = () => page.evaluate(() => ({ text: window.chatDraftView.messageInput.value, ids: window.chatDraftView.inputAttachments.value.map(a => a.media_id) }))
  const go = path => page.evaluate(path => window.draftTest.router.push(path), path)
  await boot()
  await page.evaluate(() => {
    window.draftTest.drop(1, [11, 12])
    window.chatDraftView.messageInput.value = 'Compare these images'
  })
  await go('/browse')
  await page.evaluate(() => { window.draftTest.drop(1, [12, 13]); window.draftTest.drop(2, [21]) })
  await go('/chat/2')
  await expect.poll(state).toEqual({ text: '', ids: [21] })
  await page.evaluate(() => { window.chatDraftView.messageInput.value = 'Second chat' })
  await go('/chat/1')
  await expect.poll(state).toEqual({ text: 'Compare these images', ids: [11, 12, 13] })
  await boot()
  await expect.poll(state).toEqual({ text: 'Compare these images', ids: [11, 12, 13] })
  // Upload completion must target the draft that initiated it.
  await page.locator('input[type=file]').setInputFiles({ name: 'upload.png', mimeType: 'image/png', buffer: Buffer.from('image') })
  await expect.poll(() => Boolean(releaseUpload)).toBe(true)
  await go('/chat/2')
  releaseUpload()
  await go('/embedded/1')
  await expect.poll(state).toEqual({ text: 'Compare these images', ids: [11, 12, 13, 31] })
  await go('/embedded/2')
  await expect.poll(state).toEqual({ text: 'Second chat', ids: [21] })
  await go('/embedded/1')
  await expect.poll(state).toEqual({ text: 'Compare these images', ids: [11, 12, 13, 31] })
  await page.getByRole('button', { name: 'Remove attachment' }).last().click()
  await go('/chat/1')
  await expect.poll(state).toEqual({ text: 'Compare these images', ids: [11, 12, 13] })
  rejectSend = true
  await page.evaluate(() => { void window.chatDraftView.sendMessage() })
  await expect.poll(() => Boolean(releaseSend)).toBe(true)
  await go('/chat/2')
  await page.evaluate(() => window.draftTest.drop(1, [14]))
  releaseSend()
  await expect.poll(state).toEqual({ text: 'Second chat', ids: [21] })
  await go('/chat/1')
  await expect.poll(state).toEqual({ text: 'Compare these images', ids: [11, 12, 13, 14] })
  rejectSend = false
  await page.evaluate(() => window.chatDraftView.sendMessage())
  await expect.poll(state).toEqual({ text: '', ids: [] })
  await boot()
  await expect.poll(state).toEqual({ text: '', ids: [] })
  // Identical chat IDs in different profiles must never share drafts.
  await go('/chat/2')
  await expect.poll(state).toEqual({ text: 'Second chat', ids: [21] })
  await page.evaluate(() => localStorage.setItem('profileId', 'another-profile'))
  await boot()
  await go('/chat/2')
  await expect.poll(state).toEqual({ text: '', ids: [] })
  await page.evaluate(() => localStorage.removeItem('profileId'))
  await boot()
  await go('/chat/2')
  await expect.poll(state).toEqual({ text: 'Second chat', ids: [21] })
  assert.deepEqual(errors, [])
})
