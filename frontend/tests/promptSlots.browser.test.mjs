import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Making and opening slots in the prompt editor (Fluent): underlined phrases and "Vary
// this", `<` around a selection, the suggestions under the text, and the open-slot event.
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
const LOOKS = [{ text: 'candid phone snapshot, slightly off-center, harsh desk lamp light', label: 'phone snapshot' },
  { text: 'editorial portrait, 85mm lens, soft window light from the left', label: 'editorial portrait' }]
const ADDS = [{ text: 'a stack of books on the desk', label: 'books' }, { text: 'rain streaking the window', label: 'rain' }]

async function open(t, { start = PROMPT, theme = 'dark', how } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 900, height: 700 }, deviceScaleFactor: 2 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const calls = { suggest: [] }
  await page.route('**/*', async route => {
    const url = route.request().url()
    if (url.endsWith('/prompt-programs/suggest')) {
      const body = route.request().postDataJSON()
      calls.suggest.push(body)
      const i = body.prompt.indexOf('young man')
      const vary = i < 0 || body.prompt[i - 1] === '<' ? [] : [{ from: i, to: i + 9, text: 'young man', label: 'different young men', ...(how ? { mode: how } : {}) }]
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ vary, looks: LOOKS, adds: ADDS }) })
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
const modes = page => page.evaluate(() => window.modes)
const offered = page => page.locator('[data-slot-offer] [data-vary]')

test('a phrase Fluent underlines becomes a slot with Vary this, and opens', async t => {
  const { page, editor, calls, shot } = await open(t)
  await expect(page.locator('.cm-could-vary')).toHaveText('young man', { timeout: 3000 })
  assert.deepEqual(calls.suggest, [{ project_id: 7, prompt: PROMPT }])
  await expect(page.locator('[data-slot-vary]')).toHaveText(['different young men'])
  await expect(page.locator('[data-slot-look-chip]')).toHaveText(['phone snapshot', 'editorial portrait'])
  await expect(page.locator('[data-slot-add]')).toHaveText(['books', 'rain'])
  await shot('underlined')

  await page.locator('.cm-could-vary').click()
  await expect(offered(page)).toHaveText(['Vary this', 'Flesh out this'])
  await shot('vary-offer')
  await page.locator('[data-vary="kind"]').click()
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
  assert.deepEqual(await modes(page), [], 'Vary is how a slot starts')
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

test('every underline offers both, Suggest\'s way first; each makes a slot that starts that way', async t => {
  for (const [how, order, pick, said] of [
    ['one', ['one', 'kind'], 'kind', [[1, 'kind']]],
    ['one', ['one', 'kind'], 'one', [[1, 'one']]],
    ['kind', ['kind', 'one'], 'one', [[1, 'one']]],
  ]) {
    const { page, shot } = await open(t, { how })
    await page.locator('.cm-could-vary').click()
    await expect(offered(page)).toHaveCount(2)
    assert.deepEqual(await offered(page).evaluateAll(b => b.map(e => e.dataset.vary)), order)
    if (how === 'one') await shot('flesh-out-offer')
    await page.locator(`[data-vary="${pick}"]`).click()
    await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
    await expect.poll(() => modes(page)).toEqual(said)
    await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'young man']])
    await expect(offered(page)).toHaveCount(0)
  }
})

test('the offer by keyboard: Tab into it, arrows between, Enter picks, Escape goes back', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a porch' })
  await editor.click()
  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  await expect(offered(page)).toHaveText(['Vary this', 'Flesh out this'])
  await page.keyboard.press('Tab')
  await expect(page.locator('[data-vary="kind"]')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(offered(page)).toHaveCount(0)
  await expect(editor).toBeFocused()
  assert.equal(await text(page), 'a cat on a porch')

  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  await expect(offered(page)).toHaveCount(2)
  await page.keyboard.press('Tab')
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-vary="one"]')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect.poll(() => text(page)).toBe('a cat on a <porch>')
  await expect.poll(() => modes(page)).toEqual([[1, 'one']])
  await expect(editor).toBeFocused()
})

test('selected words: Vary this under them, and < wraps them; with nothing selected < types', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a porch' })
  // Select "porch" from the end of the line.
  await editor.click()
  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  await expect(page.locator('[data-vary="kind"]')).toBeVisible()
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

test('on touch, Vary this floats by the words and is not turned into a bottom sheet', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a porch' })
  // Touch converts every fixed menu-tier box into a sheet with a full-screen backdrop,
  // which would cover the text and take the taps and drags that adjust the selection.
  await page.evaluate(() => document.documentElement.setAttribute('data-pointer', 'coarse'))
  await editor.click()
  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  const chip = page.locator('[data-slot-offer]')
  await expect(chip).toBeVisible()
  const words = await editor.boundingBox()
  const box = await chip.boundingBox()
  assert.ok(box.width < 320, `chip width ${box.width}: not a full-width sheet`)
  await expect(offered(page)).toHaveText(['Vary this', 'Flesh out this'])
  for (const b of await offered(page).all()) assert.ok((await b.boundingBox()).height >= 43, 'a touch-sized target')
  assert.ok(box.y < words.y + words.height + 60, `chip at ${box.y}: beside the words, not at the bottom`)
  assert.equal(await page.locator('[data-sheet-backdrop]').count(), 0)
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

test('a vary chip wraps its words and opens the slot, as Vary this does', async t => {
  const { page } = await open(t)
  await page.locator('[data-slot-vary="young man"]').click()
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'young man']])
  await expect(page.locator('[data-slot-vary]')).toHaveCount(0)
})

test('an add writes its words as they are, opens nothing, and undoes in one step', async t => {
  const { page, shot } = await open(t)
  await page.locator('[data-slot-add="books"]').click()
  await expect.poll(() => text(page)).toBe(`${PROMPT}, a stack of books on the desk`)
  assert.deepEqual(await opened(page), [])
  // It is in the prompt now: its chip goes; the other stays.
  await expect(page.locator('[data-slot-add]')).toHaveText(['rain'])
  await shot('added')
  await page.locator('.cm-content').click()
  await page.keyboard.press('Control+z')
  await expect.poll(() => text(page)).toBe(PROMPT)
})

test('a look writes its words, and the other looks go', async t => {
  const { page } = await open(t)
  await page.locator('[data-slot-look-chip="editorial portrait"]').click()
  await expect.poll(() => text(page)).toBe(`${PROMPT}, ${LOOKS[1].text}`)
  await expect(page.locator('[data-slot-look-chip]')).toHaveCount(0)
  await expect(page.locator('[data-slot-add]')).toHaveText(['books', 'rain'])
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
