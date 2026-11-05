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
  build: { write: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/chatInputScroll.ts', import.meta.url)),
    name: 'ChatInputScrollTest', formats: ['iife'],
  } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

for (const width of [390, 1200]) test(`chat input keeps long drafts and the caret reachable at ${width}px`, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height: 844 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill(new URL(route.request().url()).pathname === '/'
    ? { contentType: 'text/html', body: '<meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div>' }
    : { json: {} }))
  await page.goto('http://chat-input.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) {
    await page.addStyleTag({ content: String(asset.source) })
  }
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  const input = page.locator('textarea')
  const metrics = () => input.evaluate(el => ({
    height: el.clientHeight, content: el.scrollHeight, top: el.scrollTop,
    line: parseFloat(getComputedStyle(el).lineHeight),
    bottomGap: el.scrollHeight - el.clientHeight - el.scrollTop,
  }))
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))

  // Actual keyboard input must follow the caret beyond the ten-line limit.
  await input.fill('Line 1')
  for (let line = 2; line <= 22; line++) {
    await input.press('Shift+Enter')
    await input.pressSequentially(`Line ${line}`)
    await settle()
  }
  let state = await metrics()
  assert.ok(state.content > state.height * 2, JSON.stringify(state))
  assert.ok(state.height <= state.line * 10 + 1, JSON.stringify(state))
  assert.ok(state.bottomGap <= state.line, `caret below viewport: ${JSON.stringify(state)}`)

  // Manual scrolling must stay put, including through an explicit resize.
  await input.hover()
  await page.mouse.wheel(0, -160)
  await expect.poll(async () => (await metrics()).bottomGap).toBeGreaterThan(100)
  const scrolledTop = (await metrics()).top
  await page.evaluate(() => window.chatInputScrollTest.composer.value.autoResize())
  await settle()
  assert.ok(Math.abs((await metrics()).top - scrolledTop) <= 1)
  await page.mouse.wheel(0, 1000)
  await expect.poll(async () => (await metrics()).bottomGap).toBeLessThan(2)

  // Keyboard navigation and editing near either end reveal that caret.
  await input.press('Control+Home')
  await expect.poll(async () => (await metrics()).top).toBeLessThan(state.line)
  await input.press('Shift+Enter')
  await settle()
  assert.ok((await metrics()).top < state.line * 2)
  await input.press('Control+End')
  await input.press('Shift+Enter')
  await settle()
  assert.ok((await metrics()).bottomGap <= state.line)
  assert.equal(await page.evaluate(() => window.chatInputScrollTest.submits), 0)

  // Clearing shrinks the field; restoring a draft sizes it without typing.
  await page.evaluate(() => { window.chatInputScrollTest.draft.text = '' })
  await settle()
  state = await metrics()
  assert.ok(state.height < state.line * 4)
  assert.equal(state.top, 0)
  await page.evaluate(() => { window.chatInputScrollTest.draft.text = 'Restored\n'.repeat(25) })
  await settle()
  state = await metrics()
  assert.ok(state.content > state.height)
  assert.ok(state.height <= state.line * 10 + 1)
  assert.deepEqual(errors, [])
})
