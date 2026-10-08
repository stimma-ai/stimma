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
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/mobileAutofocus.ts', import.meta.url)), name: 'AutofocusTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
for (const [width, touch] of [[390, true], [752, true], [1100, true], [1440, false]]) test(`navigation focus at ${width}px, touch=${touch}`, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height: 844 }, hasTouch: touch })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div>' })
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true }], global_default: 'test', llm_configured: true } })
    if (path.includes('/projects/9')) return route.fulfill({ json: { id: 9, name: 'Test project' } })
    if (path.includes('/chats') || path.includes('/media')) return route.fulfill({ json: { items: [], total: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto(`http://autofocus.test/?pointer=${touch ? 'coarse' : 'fine'}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  for (const path of ['/', '/projects/9/overview', '/chats', '/', '/projects/9/overview']) {
    await page.evaluate(path => window.autofocusTest.router.push(path), path)
    const input = page.locator(path === '/chats' ? 'input[placeholder="Search chats..."]' : '.chat-input-textarea')
    if (touch && width < 768 && path === '/chats') {
      await expect(input).toBeHidden()
      assert.equal(await page.evaluate(() => document.activeElement.matches('input, textarea, [contenteditable="true"]')), false)
      continue
    }
    await expect(input).toBeVisible()
    if (touch) {
      await expect(input).not.toBeFocused()
      await input.tap()
      await expect(input).toBeFocused()
      await page.evaluate(() => document.activeElement.blur())
    } else await expect(input).toBeFocused()
  }
  const composer = page.locator('.chat-input-textarea')
  await composer.click()
  await page.evaluate(() => window.autofocusTest.setModal(true))
  await expect(page.locator('[data-modal-layer]')).toBeVisible()
  await expect(composer).not.toBeFocused()
  await page.evaluate(() => window.autofocusTest.setModal(false))
  if (touch) await expect(composer).not.toBeFocused()
  else await expect(composer).toBeFocused()
  // Non-input return focus still supports keyboard and assistive navigation.
  const launcher = page.locator('#overlay-launcher')
  await launcher.focus()
  await page.evaluate(() => window.autofocusTest.setModal(true))
  await expect(launcher).not.toBeFocused()
  await page.evaluate(() => window.autofocusTest.setModal(false))
  await expect(launcher).toBeFocused()
  assert.deepEqual(errors, [])
})
