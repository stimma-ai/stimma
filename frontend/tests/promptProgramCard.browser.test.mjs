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
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/promptProgramCard.ts', import.meta.url)), name: 'PromptProgramCardTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))

async function open(t, pageOptions = { viewport: { width: 900, height: 900 } }) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage(pageOptions)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html class="dark"><body><div id="app"></div></body></html>' }))
  await page.goto('http://program-card.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  t.after(() => assert.deepEqual(errors, []))
  const row = page.locator('[data-program-choices]')
  await expect(row).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.programStatus())).toBe('ready')
  const pill = id => row.locator(`[data-choice="${id}"]`)
  const card = page.locator('[data-program-card]')
  const option = text => card.locator(`[data-option="${text}"]`)
  const state = () => page.evaluate(() => window.state())
  return { page, row, pill, card, option, state }
}

test('every slot and list has a pill, untouched ones only their label', async t => {
  const { row } = await open(t)
  const labels = await row.locator('[data-choice]').allInnerTexts()
  assert.deepEqual(labels.map(s => s.trim()), ['Young man', 'Pet', 'Light', 'Season'])
  await expect(row.locator('[data-reset-all]')).toHaveCount(0)
})

test('a slot opens its chooser: the lit row, two zones, choosing adds, chips with Clear', async t => {
  const { page, pill, card, option, state } = await open(t)
  await pill('pet').click()
  await expect(card.locator('[data-default]')).toHaveText('Kinds of pet')
  await expect(card.locator('[data-default] svg')).toHaveCount(1)
  await expect(card.getByText('Instead of pet')).toBeVisible()
  await option('old basset hound').click()
  await expect.poll(state).toEqual({ pet: { values: ['old basset hound'] } })
  await expect(card.locator('[data-default] svg')).toHaveCount(0)
  await expect(card.locator('[data-chosen]')).toContainText('basset hound')
  await expect(pill('pet')).toHaveText('Petbasset hound')
  await card.locator('[data-zone-any="instead"]').click()
  await expect.poll(state).toEqual({ pet: { values: ['old basset hound'], zones: ['instead'] } })
  // A zone chosen ticks its options as covered, quietly.
  await expect(option('mug of coffee').locator('svg')).toHaveCount(1)
  await card.locator('[data-clear]').click()
  await expect.poll(state).toEqual({})
  await expect(card.locator('[data-default] svg')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)
})

test('as written draws the slot’s words; leave out reads "No light" and × puts it back', async t => {
  const { page, pill, card, row, state } = await open(t)
  await pill('pet').click()
  await card.locator('[data-as-written]').click()
  await expect.poll(state).toEqual({ pet: { values: ['pet'] } })
  await expect(pill('pet')).toHaveText('Petas written')
  await page.keyboard.press('Escape')
  await pill('light').click()
  await card.locator('[data-leave-out]').click()
  await expect(card).toHaveCount(0)
  await expect(pill('light')).toHaveText('No light')
  await expect(row.locator('[data-reset-all]')).toBeVisible()
  await row.locator('[data-reset="light"]').click()
  await expect.poll(state).toEqual({ pet: { values: ['pet'] } })
  await expect(row.locator('[data-reset-all]')).toHaveCount(0)
})

test('a person opens on its details; a detail’s chooser has groups and a way back', async t => {
  const { pill, card, option, row, state } = await open(t)
  await pill('young_man').click()
  const rows = await card.locator('[data-row]').evaluateAll(rs => rs.map(r => r.dataset.row))
  assert.deepEqual(rows, ['young_man.age', 'young_man.descent', 'young_man.build', 'young_man.hair', 'young_man.outfit'])
  await expect(card.locator('[data-row="young_man.age"]')).toContainText('young')
  await card.locator('[data-row="young_man.hair"]').click()
  await expect(card.locator('[data-back]')).toHaveText('Young man')
  await card.locator('[data-part="long"]').click()
  assert.deepEqual(await card.locator('[data-option]').evaluateAll(rs => rs.map(r => r.dataset.option)), ['man bun', 'long waves', 'shoulder-length curls'])
  await card.locator('[data-any-part]').click()
  await expect.poll(state).toEqual({ 'young_man.hair': { groups: { length: ['long'] } } })
  await expect(card.locator('[data-chosen]')).toContainText('any long')
  await card.locator('[data-back]').click()
  await expect(card.locator('[data-row="young_man.hair"]')).toContainText('long')
  await expect(row.locator('[data-choice="young_man.hair"]')).toHaveText('Hairlong')
  // The row's × puts the detail back.
  await card.locator('[data-reset="young_man.hair"]').click()
  await expect.poll(state).toEqual({})
  // An outfit's options read short; its colors sit inside it, as swatches.
  await card.locator('[data-row="young_man.outfit"]').click()
  await expect(option('a {main} flannel shirt and {neutral} jeans')).toContainText('flannel and jeans')
  await expect(option('a {main} suit with a {accent} tie')).toContainText('a … suit with a … tie')
  await card.locator('[data-follower="young_man.outfit.colors"]').click()
  await expect(card.locator('[data-back]')).toHaveText('Outfit')
  await option('navy, white and gray').click()
  await expect(row.locator('[data-choice="young_man.outfit.colors"] [data-swatches] span')).toHaveCount(3)
})

test('three details chosen fold into the person’s pill; its × puts them all back', async t => {
  const { page, row, pill, state } = await open(t)
  await page.evaluate(() => window.setState({
    'young_man.age': { values: ['24-year-old'] }, 'young_man.hair': { values: ['buzz cut'] }, 'young_man.build': { off: true },
  }))
  await expect(pill('young_man')).toHaveText('Young man24-year-old, no build, buzz cut')
  await expect(row.locator('[data-choice="young_man.hair"]')).toHaveCount(0)
  await row.locator('[data-reset="young_man"]').click()
  await expect.poll(state).toEqual({})
})

test('search finds, Add chooses the user’s own option, Escape steps back out', async t => {
  const { page, pill, card, option, state } = await open(t)
  await pill('young_man').click()
  await card.locator('[data-row="young_man.descent"]').click()
  const search = card.getByPlaceholder('Search')
  await search.fill('kor')
  assert.deepEqual(await card.locator('[data-option]').evaluateAll(rs => rs.map(r => r.dataset.option)), ['Korean'])
  await search.fill('Basque')
  await card.locator('[data-add]').click()
  await expect.poll(state).toEqual({ 'young_man.descent': { add: ['Basque'], values: ['Basque'] } })
  await expect(option('Basque').locator('[aria-label="Delete Basque"]')).toHaveCount(1)
  await search.fill('x')
  await page.keyboard.press('Escape')
  await expect(search).toHaveValue('')
  await page.keyboard.press('Escape')
  await expect(card.locator('[data-panel]')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)
})

test('More like these adds options to the list', async t => {
  const { pill, card, option, state } = await open(t)
  await pill('pet').click()
  await card.locator('[data-more]').click()
  await expect(option('sleepy ferret')).toBeVisible()
  await expect.poll(state).toEqual({ pet: { add: ['three-legged greyhound', 'sleepy ferret'] } })
})

test('a slot just made opens on "Writing options…" and fills in when it is read', async t => {
  const { page, card } = await open(t)
  await page.evaluate(() => window.newSlot(700))
  await expect(card.locator('[data-writing]')).toContainText('Writing options…')
  await expect(card.locator('[data-default]')).toHaveText('Kinds of cat', { timeout: 5000 })
})

test('a submit sends the choices as program.choices', async t => {
  const { page, pill, card, option } = await open(t)
  await pill('list1').click()
  await option('autumn').click()
  const payload = await page.evaluate(() => window.payload())
  assert.deepEqual(payload, { enabled: true, choices: { list1: { values: ['autumn'] } } })
  const pools = await page.evaluate(() => window.calls.filter(c => c.url === 'pools').at(-1).body)
  assert.deepEqual(pools.choices, { list1: { values: ['autumn'] } })
  assert.equal(pools.key, 'k3')
  // A list keeps exactly what the user gave: nothing to add, nothing to write.
  await expect(card.locator('[data-more]')).toHaveCount(0)
})

test('on a phone the card is a bottom sheet', async t => {
  const { pill, card } = await open(t, { viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true })
  await pill('pet').click()
  await expect(card).toBeVisible()
  const box = await card.boundingBox()
  assert.ok(box && box.y + box.height > 700, `sheet at ${JSON.stringify(box)}`)
})
