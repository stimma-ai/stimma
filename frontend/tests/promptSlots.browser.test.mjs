import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Making and opening slots in the prompt editor (Fluent): underlined phrases and "Vary
// this", `<` around a selection, the adds under the text, and the open-slot event.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/promptSlots.ts', import.meta.url)), name: 'PromptSlotsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

const PROMPT = 'dorm room with a young man'

async function open(t, { start = PROMPT, theme = 'dark', add = 'ok' } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 900, height: 700 }, deviceScaleFactor: 2 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const calls = { suggest: [], add: [] }
  await page.route('**/*', async route => {
    const url = route.request().url()
    if (url.endsWith('/prompt-programs/suggest')) {
      const body = route.request().postDataJSON()
      calls.suggest.push(body)
      const i = body.prompt.indexOf('young man')
      const vary = i < 0 ? [] : [{ from: i, to: i + 9, text: 'young man' }]
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ vary, adds: [{ name: 'light', label: 'light' }, { name: 'camera', label: 'camera' }] }) })
    }
    if (url.endsWith('/prompt-programs/add')) {
      const body = route.request().postDataJSON()
      calls.add.push(body)
      await new Promise(r => setTimeout(r, 400))
      if (add !== 'ok') return route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"no"}' })
      const next = `${body.prompt}, lit by <${body.name}>`
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ prompt: next, slot: { from: next.length - body.name.length - 2, to: next.length } }) })
    }
    if (url.includes('/api/')) return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    return route.fulfill({ contentType: 'text/html', body: `<html data-theme="${theme}"><body><script>window.START = ${JSON.stringify(start)}</script><div id="app"></div></body></html>` })
  })
  await page.goto('http://prompt-slots.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  const editor = page.locator('.cm-content')
  await editor.waitFor()
  t.after(() => assert.deepEqual(errors, []))
  const shot = async file => { if (SHOTS) await page.locator('#app').screenshot({ path: `${SHOTS}/${file}.png` }) }
  return { page, editor, calls, shot }
}

const text = page => page.evaluate(() => window.text())
const opened = page => page.evaluate(() => window.opened)

test('a phrase Fluent underlines becomes a slot with Vary this, and opens', async t => {
  const { page, editor, calls, shot } = await open(t)
  await expect(page.locator('.cm-could-vary')).toHaveText('young man', { timeout: 3000 })
  assert.deepEqual(calls.suggest, [{ tool_id: 'test-tool', prompt: PROMPT }])
  await expect(page.locator('[data-slot-add]')).toHaveText(['light', 'camera'])
  await shot('underlined')

  await page.locator('.cm-could-vary').click()
  await expect(page.locator('[data-vary]')).toBeVisible()
  await shot('vary-offer')
  await page.locator('[data-vary]').click()
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
  await expect(editor.locator('.cm-slot')).toHaveText('<young man>')
  await expect(page.locator('[data-vary]')).toHaveCount(0)
  const [o] = await opened(page)
  assert.equal(o.n, 1)
  assert.equal(o.words, 'young man')
  assert.ok(o.rect.width > 20 && o.rect.height > 10, 'the slot\'s place on screen')

  // Clicking the slot opens it again.
  await editor.locator('.cm-slot').click()
  await expect.poll(async () => (await opened(page)).length).toBe(2)
  assert.deepEqual((await opened(page))[1].words, 'young man')
})

test('selected words: Vary this under them, and < wraps them; with nothing selected < types', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a porch' })
  // Select "porch" from the end of the line.
  await editor.click()
  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  await expect(page.locator('[data-vary]')).toBeVisible()
  await page.keyboard.type('<')
  await expect.poll(() => text(page)).toBe('a cat on a <porch>')
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'porch']])

  // Undo takes the brackets off in one step.
  await page.keyboard.press('Control+z')
  await expect.poll(() => text(page)).toBe('a cat on a porch')

  await page.keyboard.press('End')
  await page.keyboard.type(' <')
  await expect.poll(() => text(page)).toBe('a cat on a porch <')
})

test('no wrapping in a comment line or inside a list', async t => {
  const { page, editor } = await open(t, { start: '# a young man\na {red|blue} coat' })
  await editor.click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.press('End')
  for (let i = 0; i < 3; i++) await page.keyboard.press('Shift+ArrowLeft')
  await page.waitForTimeout(250)
  await expect(page.locator('[data-vary]')).toHaveCount(0)
  await page.keyboard.type('<')
  await expect.poll(() => text(page)).toBe('# a young <\na {red|blue} coat')
  assert.deepEqual(await opened(page), [])
})

test('an add is written into the prompt as a slot, opens, and undoes in one step', async t => {
  const { page, calls, shot } = await open(t)
  const chip = page.locator('[data-slot-add="light"]')
  await chip.click()
  await expect(chip.locator('.animate-spin')).toBeVisible()
  await shot('adding')
  await expect.poll(() => text(page)).toBe(`${PROMPT}, lit by <light>`)
  assert.deepEqual(calls.add, [{ tool_id: 'test-tool', prompt: PROMPT, name: 'light' }])
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'light']])
  // Light is in the prompt now: its chip goes once Suggest has seen it.
  await expect(page.locator('[data-slot-add]')).toHaveText(['camera'], { timeout: 3000 })
  await shot('added')

  await page.locator('.cm-content').click()
  await page.keyboard.press('Control+z')
  await expect.poll(() => text(page)).toBe(PROMPT)
})

test('an add that fails changes nothing', async t => {
  const { page } = await open(t, { add: 'fail' })
  await page.locator('[data-slot-add="light"]').click()
  await page.waitForTimeout(700)
  assert.equal(await text(page), PROMPT)
  assert.deepEqual(await opened(page), [])
  await expect(page.locator('[data-slot-add]')).toHaveText(['light', 'camera'])
})

test('Raw and Direct: no suggestions, slots don\'t open; names are marked in every mode', async t => {
  const { page, editor, calls } = await open(t, { start: '' })
  await page.waitForTimeout(1200)
  assert.equal(calls.suggest.length, 0, 'nothing asked for an empty prompt')

  await page.evaluate(() => window.setWay('direct'))
  await page.evaluate(() => window.setText('a <young man> with {{hairstyle}} in {{outfit}}'))
  await expect(editor.locator('.cm-named-wildcard')).toHaveText('{{hairstyle}}')
  await expect(editor.locator('.cm-unknown-name')).toHaveText('{{outfit}}')
  await expect(editor.locator('.cm-slot')).toHaveText('<young man>')
  await editor.locator('.cm-slot').click()
  await page.waitForTimeout(1200)
  assert.equal(calls.suggest.length, 0)
  assert.deepEqual(await opened(page), [])
  await expect(page.locator('[data-slot-adds]')).toHaveCount(0)

  await page.evaluate(() => window.setWay('raw'))
  await expect(editor.locator('.cm-slot, .cm-unknown-name')).toHaveCount(0)
  await page.waitForTimeout(1200)
  assert.equal(calls.suggest.length, 0)
})

test('light theme', async t => {
  const { page, shot } = await open(t, { start: 'a <young man> in a {red|blue} coat with {{hairstyle}}, [ohwx], {{outfit}}\n# a note', theme: 'light' })
  await expect(page.locator('[data-slot-add]')).toHaveCount(2, { timeout: 3000 })
  await shot('light')
})
