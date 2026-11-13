import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Fluent's picker in the prompt card, as ToolView wires it: the real editor with its marks, the
// lines under the prompt, the slot's picker and its hover card, on the real composable against
// a stand-in server in the contract's shapes (fixtures/fluentPicker.ts). No pills: clicking a
// slot in the text opens its picker. Set PROMPT_SHOTS_DIR to save screenshots of the key states.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/fluentPicker.ts', import.meta.url)), name: 'FluentPickerTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

const KOREAN = 'dominant young woman of Korean descent with a sharp black bob and a cool, level stare'
const SWEDISH = 'dominant young woman of Swedish descent with close-cropped bleached hair and a septum ring'
const MIRROR = 'mirror selfie in a smudged full-length mirror'
const WINDOW = 'soft window light from the left'

async function open(t, { width = 900, height = 860, mobile = false, theme = 'dark', before = '' } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2, hasTouch: mobile, isMobile: mobile, colorScheme: theme })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: `<html data-theme="${theme}" class="${theme}"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body class="bg-app"><script>${before}</script><div id="app"></div></body></html>` }))
  await page.goto('http://fluent-picker.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  t.after(() => assert.deepEqual(errors, []))
  await expect.poll(() => page.evaluate(() => window.programStatus())).toBe('ready')
  const mark = n => page.locator(`[data-slot-n="${n}"]`)
  await expect(mark(1)).toHaveAttribute('data-slot-look', 'varying')
  const picker = page.locator('[data-picker]')
  const variant = text => picker.locator(`[data-variant="${text}"]`)
  const line = id => page.locator(`[data-line="${id}"]`)
  const state = () => page.evaluate(() => window.state())
  const calls = url => page.evaluate(u => window.calls.filter(c => c.url === u).map(c => c.body), url)
  const shot = async file => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${file}.png` }) }
  const tap = mobile ? l => l.tap() : l => l.click()
  return { page, mark, picker, variant, line, state, calls, shot, tap }
}

test('no pills: a slot in the text opens its picker, anchored to it, on Any of these', async t => {
  const { page, mark, picker, variant, shot } = await open(t)
  await expect(page.locator('[data-program-choices]')).toHaveCount(0)
  await expect(page.locator('[data-slot-lines]')).toHaveCount(0)
  await mark(1).click()
  await expect(picker.locator('[data-picker-title]')).toHaveText('dominant young woman')
  await expect(picker.locator('[data-any] svg')).toHaveCount(1)
  await expect(picker.locator('[data-as-written]')).toContainText('dominant young woman')
  await expect(variant(KOREAN)).toBeVisible()
  // The slot's own words read quieter than what the writer added.
  await expect(variant(KOREAN).locator('[data-kept]')).toHaveText('dominant young woman')
  // Hung from the slot: just under it.
  const slotBox = await mark(1).boundingBox()
  const box = await picker.boundingBox()
  assert.ok(box.y >= slotBox.y + slotBox.height && box.y < slotBox.y + slotBox.height + 20, `picker at ${JSON.stringify(box)}, slot ${JSON.stringify(slotBox)}`)
  // A person is what the prompt is about: no Leave out.
  await expect(picker.locator('[data-leave-out]')).toHaveCount(0)
  await shot('picker-variants')
  await page.keyboard.press('Escape')
  await expect(picker).toHaveCount(0)
  await mark(4).click()
  await expect(picker.locator('[data-picker-title]')).toHaveText('lighting')
  await expect(picker.locator('[data-leave-out]')).toBeVisible()
})

test('each mark: tint, sheen while written, a dot once set, strike when left out, no tint as written', async t => {
  const { page, mark, picker, variant, state, shot } = await open(t)
  for (const n of [1, 2, 3, 4]) await expect(mark(n)).toHaveAttribute('data-slot-look', 'varying')
  // Pin one variant: a dot after the slot.
  await mark(2).click()
  await variant(MIRROR).click()
  await expect.poll(state).toEqual({ selfie: { values: [MIRROR] } })
  await expect(mark(2)).toHaveAttribute('data-slot-look', 'pinned')
  await expect(picker.locator('[data-state="pinned"]')).toHaveText('Pinned')
  await expect(page.locator('[data-slot-glyph="2"].cm-slot-glyph-dot')).toHaveCount(1)
  // Several: still one dot.
  await variant('flash selfie at arm’s length, red-eye and hard shadows').click()
  await expect(mark(2)).toHaveAttribute('data-slot-look', 'several')
  await expect(page.locator('[data-slot-glyph="2"].cm-slot-glyph-dot')).toHaveCount(1)
  await page.keyboard.press('Escape')
  // As written: no tint, no dot.
  await mark(3).click()
  await picker.locator('[data-as-written]').click()
  await expect(mark(3)).toHaveAttribute('data-slot-look', 'written')
  await expect(page.locator('[data-slot-glyph="3"]')).toHaveCount(0)
  const bg = await mark(3).evaluate(el => getComputedStyle(el).backgroundColor)
  assert.match(bg, /rgba\(0, 0, 0, 0\)|transparent/)
  await page.keyboard.press('Escape')
  // Left out: struck through; the picker closes.
  await mark(4).click()
  await picker.locator('[data-leave-out]').click()
  await expect(picker).toHaveCount(0)
  await expect(mark(4)).toHaveAttribute('data-slot-look', 'off')
  assert.match(await mark(4).evaluate(el => getComputedStyle(el).textDecorationLine), /line-through/)
  await expect.poll(state).toEqual({ selfie: { values: [MIRROR, 'flash selfie at arm’s length, red-eye and hard shadows'] }, clothing: { as_written: true }, lighting: { off: true } })
  await shot('marks-chosen')
  // The glyph opens its slot, as its words do.
  await page.locator('[data-slot-glyph="2"]').click()
  await expect(picker.locator('[data-picker-title]')).toHaveText('type of selfie')
})

test('a slot whose variants are being written shows a sheen, and its picker says so', async t => {
  const { page, mark, picker, shot } = await open(t, { before: 'window.HOLD = ["lighting"]' })
  await expect(mark(4)).toHaveAttribute('data-slot-look', 'writing')
  assert.match(await mark(4).evaluate(el => getComputedStyle(el).animationName), /sheen/)
  await shot('marks-writing')
  await mark(4).click()
  await expect(picker.locator('[data-writing]')).toContainText('Writing variants')
  await expect(picker.locator('[data-state="writing"]')).toBeVisible()
  await expect(picker.locator('[data-any]')).toHaveCount(0)
  await expect(picker.locator('[data-as-written]')).toBeVisible()
  // Written: the picker fills in, and the slot takes its tint.
  await page.evaluate(() => window.release('lighting'))
  await expect(picker.locator(`[data-variant="${WINDOW}"]`)).toBeVisible({ timeout: 6000 })
  await expect(mark(4)).toHaveAttribute('data-slot-look', 'varying')
})

test('lines: one per set slot; unticking releases the pin and keeps the line, × removes it', async t => {
  const { page, mark, picker, variant, line, state, shot } = await open(t)
  await mark(4).click()
  await variant(WINDOW).click()
  await page.keyboard.press('Escape')
  await mark(3).click()
  await picker.locator('[data-as-written]').click()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-line]')).toHaveCount(2)
  await expect(line('clothing')).toContainText('Clothing')
  await expect(line('clothing')).toContainText('as written')
  await expect(line('lighting')).toContainText('Lighting')
  await expect(line('lighting')).toContainText(WINDOW)
  await shot('lines')
  // Untick: the slot varies again, the line stays, struck and unticked.
  await line('lighting').locator('[data-line-tick]').click()
  await expect.poll(state).toEqual({ clothing: { as_written: true } })
  await expect(line('lighting').locator('[data-line-tick]')).toHaveAttribute('aria-checked', 'false')
  await expect(mark(4)).toHaveAttribute('data-slot-look', 'varying')
  // Tick again: back as it was.
  await line('lighting').locator('[data-line-tick]').click()
  await expect.poll(state).toEqual({ clothing: { as_written: true }, lighting: { values: [WINDOW] } })
  await expect(mark(4)).toHaveAttribute('data-slot-look', 'pinned')
  // ×: varies, and the line goes.
  await line('lighting').hover()
  await line('lighting').locator('[data-line-remove]').click()
  await expect.poll(state).toEqual({ clothing: { as_written: true } })
  await expect(line('lighting')).toHaveCount(0)
  // A released line's × drops it too.
  await line('clothing').locator('[data-line-tick]').click()
  await line('clothing').hover()
  await line('clothing').locator('[data-line-remove]').click()
  await expect(page.locator('[data-line]')).toHaveCount(0)
  // A line's words open its slot's picker.
  await mark(2).click()
  await variant(MIRROR).click()
  await page.keyboard.press('Escape')
  await line('selfie').locator('[data-line-open]').click()
  await expect(picker.locator('[data-picker-title]')).toHaveText('type of selfie')
})

test('More like these waits on the writer with a spinner, then marks what is new', async t => {
  const { page, mark, picker, variant, calls, state, shot } = await open(t)
  await page.evaluate(() => window.slowMore(900))
  await mark(3).click()
  const more = picker.locator('[data-more]')
  await more.click()
  await expect(more).toBeDisabled()
  await expect(more.locator('.animate-spin, [role="status"], svg')).toHaveCount(1)
  await expect(variant('a denim jacket slightly open in the front')).toBeVisible({ timeout: 4000 })
  await expect(more).toBeEnabled()
  await expect(variant('a denim jacket slightly open in the front').locator('[data-new]')).toHaveCount(1)
  await expect(variant('a white cardigan slightly open in the front').locator('[data-new]')).toHaveCount(0)
  // The server names the words every variant keeps: those read quieter.
  await expect(variant('a white cardigan slightly open in the front').locator('[data-kept]')).toHaveText('open in the front')
  const [sent] = await calls('options')
  assert.equal(sent.choice_id, 'clothing')
  assert.deepEqual(sent.choices, {})
  await shot('more-like-these')
  // Search finds; Add pins a phrase of the user's own.
  await picker.locator('input').fill('velvet')
  await expect(picker.getByText('No matches')).toBeVisible()
  await picker.locator('[data-add]').click()
  await expect.poll(state).toEqual({ clothing: { values: ['velvet'], add: ['velvet'] } })
})

test('descent: Region > heritage; a pick pins that seed, filters the variants and writes for it', async t => {
  const { page, mark, picker, variant, line, state, calls, shot } = await open(t)
  await mark(1).click()
  await picker.getByRole('radio', { name: /Descent/ }).click()
  await expect(picker.locator('[data-descent-any] svg')).toHaveCount(1)
  await expect(picker.locator('[data-region]')).toHaveCount(4)
  await picker.locator('[data-region="East Asia"]').click()
  await picker.locator('[data-heritage="Korean"]').click()
  await expect.poll(state).toEqual({ woman: { seeds: { descent: { values: ['Korean'] } } } })
  await picker.locator('[data-region-any="East Asia"]').click()
  await expect.poll(state).toEqual({ woman: { seeds: { descent: { groups: { region: ['East Asia'] } } } } })
  await picker.locator('[data-regions]').click()
  await expect(picker.locator('[data-region="East Asia"]')).toContainText('Any')
  await expect(picker.locator('[data-chosen]')).toContainText('East Asia')
  await shot('picker-descent')
  // The pick reaches the server with /pools, and the variants list only what matches.
  await expect.poll(async () => (await calls('pools')).at(-1)?.choices?.woman).toEqual({ seeds: { descent: { groups: { region: ['East Asia'] } } } })
  await picker.getByRole('radio', { name: /Variants/ }).click()
  await expect(variant(KOREAN)).toBeVisible()
  await expect(variant(SWEDISH)).toHaveCount(0)
  await expect(mark(1)).toHaveAttribute('data-slot-look', 'several')
  await expect(line('woman')).toContainText('East Asia')
  // A heritage nothing in the pool has: written for, with a quiet spinner, then listed.
  await picker.getByRole('radio', { name: /Descent/ }).click()
  await picker.locator('input').fill('dan')
  await picker.locator('[data-heritage="Danish"]').click()
  await picker.getByRole('radio', { name: /Variants/ }).click()
  await expect(picker.locator('[data-rewriting]')).toContainText('Writing variants for East Asia or Danish', { timeout: 3000 })
  await expect(variant('dominant young woman of Danish descent with long waves')).toBeVisible({ timeout: 6000 })
})

test('gender: narrowed to what the words allow; a pick pins it and shows on the line', async t => {
  const { mark, picker, line, state, shot } = await open(t)
  await mark(1).click()
  await picker.getByRole('radio', { name: /Gender/ }).click()
  await expect(picker.locator('[data-gender]')).toHaveText(['Woman', 'Trans woman'])
  await picker.locator('[data-gender="trans woman"]').click()
  await expect.poll(state).toEqual({ woman: { seeds: { gender: { values: ['trans woman'] } } } })
  await expect(picker.getByRole('radio', { name: /Gender/ })).toContainText('1')
  await shot('picker-gender')
  await expect(line('woman')).toContainText('Trans woman')
  // Variants written for someone else go from the list.
  await picker.getByRole('radio', { name: /Variants/ }).click()
  await expect(picker.locator(`[data-variant="${SWEDISH}"]`)).toBeVisible()
  await expect(picker.locator(`[data-variant="${KOREAN}"]`)).toHaveCount(0)
  await picker.getByRole('radio', { name: /Gender/ }).click()
  await picker.locator('[data-gender-any]').click()
  await expect.poll(state).toEqual({})
})

test('a list of the user’s own opens its picker from the text: Any, a value, a range', async t => {
  const { page, picker, variant, line, state, shot } = await open(t)
  const list = page.locator('[data-list-n="1"]').first()
  // Nothing chosen: it keeps its list color.
  await expect(list).toHaveAttribute('data-list-look', 'varying')
  const green = await page.locator('.cm-wildcard').first().evaluate(el => getComputedStyle(el).color)
  await list.click()
  await expect(picker.locator('[data-picker-title]')).toHaveText('Season')
  const listBox = await list.boundingBox()
  const box = await picker.boundingBox()
  assert.ok(box.y >= listBox.y + listBox.height && box.y < listBox.y + listBox.height + 20, `picker at ${JSON.stringify(box)}, list ${JSON.stringify(listBox)}`)
  await expect(picker.locator('[data-any] svg')).toHaveCount(1)
  await expect(picker.locator('[data-variant]')).toHaveText(['summer', 'autumn', 'winter', 'spring'])
  await expect(picker.locator('[data-as-written]')).toHaveCount(0)
  await expect(picker.locator('[data-leave-out]')).toHaveCount(0)
  // A value.
  await variant('autumn').click()
  await expect.poll(state).toEqual({ list1: { values: ['autumn'] } })
  await expect(list).toHaveAttribute('data-list-look', 'pinned')
  await expect(page.locator('[data-list-glyph="1"].cm-slot-glyph-dot')).toHaveCount(1)
  assert.notEqual(await page.locator('.cm-list-set').first().evaluate(el => getComputedStyle(el).color), green)
  await expect(line('list1')).toContainText('autumn')
  // A range: shift-click from the last one clicked; again from an un-pinned one un-pins it.
  await variant('summer').click()
  await variant('winter').click({ modifiers: ['Shift'] })
  await expect.poll(state).toEqual({ list1: { values: ['summer', 'autumn', 'winter'] } })
  await expect(list).toHaveAttribute('data-list-look', 'several')
  await expect(line('list1')).toContainText('summer, autumn, winter')
  await shot('list-picker')
  await variant('autumn').click()
  await variant('spring').click({ modifiers: ['Shift'] })
  await expect.poll(state).toEqual({ list1: { values: ['summer'] } })
  // Any of these lets it draw from all of them again, and it takes its list color back.
  await picker.locator('[data-any]').click()
  await expect.poll(state).toEqual({})
  await expect(list).toHaveAttribute('data-list-look', 'varying')
  await page.keyboard.press('Escape')
  // Its glyph opens it too, once set.
  await page.evaluate(() => window.setState({ list1: { values: ['winter'] } }))
  await page.locator('[data-list-glyph="1"]').click()
  await expect(picker.locator('[data-picker-title]')).toHaveText('Season')
})

test('hover on a desktop shows three variants images could get', async t => {
  const { page, mark, shot } = await open(t)
  await mark(3).hover()
  const card = page.locator('[data-slot-hover]')
  await expect(card).toBeVisible()
  await shot('hover')
  await expect(card.locator('[data-hover-head]')).toHaveText('Varies · 3 variants')
  await expect(card.locator('[data-hover-sample]')).toHaveCount(3)
  await page.mouse.move(5, 5)
  await expect(card).toHaveCount(0)
})

test('Keep from this pins a variant and shows it as the same line, with the image', async t => {
  const { page, mark, line, state, shot } = await open(t)
  const run = { key: 'k1', version: 'slots-1', draws: [{ id: 'woman', value: SWEDISH }, { id: 'lighting', value: WINDOW }, { id: 'list1', value: 'autumn' }] }
  await page.evaluate(r => window.keep(r, 2), run)
  const card = page.locator('[data-keep-card]')
  await expect(card.locator('[data-keep]')).toHaveCount(3)
  await card.locator('[data-keep="woman"]').click()
  await expect.poll(state).toEqual({ woman: { values: [SWEDISH], from: 2 } })
  await expect(card.locator('[data-keep="woman"]')).toHaveAttribute('aria-checked', 'true')
  await expect(line('woman')).toContainText(SWEDISH)
  await expect(line('woman').locator('[data-line-thumb]')).toBeVisible()
  await expect(mark(1)).toHaveAttribute('data-slot-look', 'keep')
  await expect(page.locator('[data-slot-glyph="1"].cm-slot-glyph-thumb')).toHaveCount(1)
  // Where it came from never reaches the server.
  assert.deepEqual(await page.evaluate(() => window.payload().choices), { woman: { values: [SWEDISH] } })
  // A list of the user's own keeps too, and its line opens its options.
  await card.locator('[data-keep="list1"]').click()
  await expect.poll(state).toEqual({ woman: { values: [SWEDISH], from: 2 }, list1: { values: ['autumn'], from: 2 } })
  await shot('keep-from-this')
  await page.keyboard.press('Escape')
  await line('list1').locator('[data-line-open]').click()
  await expect(page.locator('[data-picker] [data-variant="summer"]')).toBeVisible()
  await page.keyboard.press('Escape')
  // Unticking on the card lets it vary again.
  await page.evaluate(r => window.keep(r, 2), run)
  await card.locator('[data-keep="woman"]').click()
  await expect(mark(1)).toHaveAttribute('data-slot-look', 'varying')
})

test('on a phone the picker is the bottom sheet, and there is no hover card', async t => {
  const { page, mark, picker, tap, shot } = await open(t, { width: 390, height: 844, mobile: true })
  await tap(mark(1))
  await expect(picker).toBeVisible()
  const box = await picker.boundingBox()
  assert.ok(box && box.y + box.height > 800 && box.width > 370, `sheet at ${JSON.stringify(box)}`)
  // Its footer is on screen without scrolling the sheet: the list gives way.
  const more = await picker.locator('[data-more]').boundingBox()
  assert.ok(more && more.y + more.height <= 844, `More like these at ${JSON.stringify(more)}`)
  await expect(page.locator('[data-slot-hover]')).toHaveCount(0)
  await shot('phone-sheet')
})
