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
  // An outfit's options read in full without their colors (the pill reads short); its
  // colors sit inside it, as swatches.
  await card.locator('[data-row="young_man.outfit"]').click()
  await expect(option('a {main} flannel shirt and {neutral} jeans')).toHaveText('a flannel shirt and jeans')
  await expect(option('a {main} suit with a {accent} tie')).toHaveText('a suit with a tie')
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

async function openDescent(t) {
  const opened = await open(t)
  await opened.pill('young_man').click()
  await opened.card.locator('[data-row="young_man.descent"]').click()
  return opened
}
const descentValues = state => async () => (await state())['young_man.descent']?.values || []

test('a plain click toggles one option and leaves the rest alone', async t => {
  const { option, state } = await openDescent(t)
  const values = descentValues(state)
  await option('Korean').click()
  await option('Indian').click()
  await expect.poll(values).toEqual(['Korean', 'Indian'])
  await option('Korean').click()
  await expect.poll(values).toEqual(['Indian'])
})

test('shift-click chooses every option from the last one clicked, without selecting text', async t => {
  const { page, option, state } = await openDescent(t)
  await option('Japanese').click()
  await option('Iranian').click({ modifiers: ['Shift'] })
  await expect.poll(descentValues(state)).toEqual(['Japanese', 'Chinese', 'Vietnamese', 'Indian', 'Iranian'])
  assert.equal(await page.evaluate(() => String(window.getSelection())), '')
})

test('shift-click on a chosen option un-chooses the range', async t => {
  const { option, state } = await openDescent(t)
  const values = descentValues(state)
  await option('Korean').click()
  await option('Indian').click({ modifiers: ['Shift'] })
  await expect.poll(values).toEqual(['Korean', 'Japanese', 'Chinese', 'Vietnamese', 'Indian'])
  await option('Chinese').click()
  await option('Korean').click({ modifiers: ['Shift'] })
  await expect.poll(values).toEqual(['Vietnamese', 'Indian'])
})

test('a shift-click range starts from an option the search has since hidden, and takes only what is shown', async t => {
  const { card, option, state } = await openDescent(t)
  await option('Korean').click()
  await card.getByPlaceholder('Search').fill('ish')
  await option('Scottish').click({ modifiers: ['Shift'] })
  await expect.poll(descentValues(state)).toEqual(['Korean', 'Turkish', 'Irish', 'Scottish'])
})

test('a shift-click range runs across both zones', async t => {
  const { pill, option, state } = await open(t)
  await pill('pet').click()
  await option('ginger tabby cat').click()
  await option('mug of coffee').click({ modifiers: ['Shift'] })
  await expect.poll(async () => (await state()).pet?.values).toEqual(['ginger tabby cat', 'old basset hound', 'gray parrot', 'mug of coffee'])
})

test('ctrl- or cmd-click toggles one option and becomes where a shift-click range starts', async t => {
  const { option, state } = await openDescent(t)
  const values = descentValues(state)
  await option('Korean').click()
  await option('Indian').click({ modifiers: ['Control'] })
  await expect.poll(values).toEqual(['Korean', 'Indian'])
  await option('Chinese').click({ modifiers: ['Shift'] })
  await expect.poll(values).toEqual(['Korean', 'Indian', 'Chinese', 'Vietnamese'])
  await option('Irish').click({ modifiers: ['Meta'] })
  await expect.poll(values).toEqual(['Korean', 'Indian', 'Chinese', 'Vietnamese', 'Irish'])
  await option('Korean').click({ modifiers: ['Meta'] })
  await expect.poll(values).toEqual(['Indian', 'Chinese', 'Vietnamese', 'Irish'])
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

test('a look-up sent before the read started does not stop the pills filling in', async t => {
  const { page, row } = await open(t)
  await page.evaluate(() => { window.slow(600, 1500); window.setPrompt(`${window.calls[0].body.prompt} and a <cat>`) })
  // The look-up is out (it will say nothing is reading); the read starts and answers first.
  await expect.poll(() => page.evaluate(() => window.calls.filter(c => c.body.cache_only && c.body.prompt.includes('<cat>')).length)).toBe(1)
  await page.evaluate(() => window.prepare())
  await expect(row.locator('[data-choice="cat"] [data-reading]')).toBeVisible()
  await expect(row.locator('[data-choice="cat"] [data-reading]')).toHaveCount(0, { timeout: 6000 })
  await expect(row.locator('[data-choice="cat"]')).toHaveText('Cat')
  const reads = await page.evaluate(() => window.calls.filter(c => c.url === 'prepare' && !c.body.cache_only).length)
  assert.equal(reads, 1)
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

test('a prompt with nothing that varies is ready with no pills and asks for no pools', async t => {
  const { page, row } = await open(t)
  await page.evaluate(() => window.setPrompt('a quiet dorm room at dusk'))
  await expect.poll(() => page.evaluate(() => window.programStatus()), { timeout: 3000 }).toBe('ready')
  await expect(row).toHaveCount(0)
  const after = await page.evaluate(() => window.calls.length)
  await page.waitForTimeout(300)
  const late = await page.evaluate(n => window.calls.slice(n).map(c => c.url), after)
  assert.ok(!late.includes('pools'), `asked ${late}`)
  assert.deepEqual(await page.evaluate(() => window.payload()), { enabled: true, choices: {} })
})

test('a reading the chat model got wrong (424 reader_failed) is a failed read, with its message', async t => {
  const { page } = await open(t)
  await page.evaluate(() => window.setPrompt('a <broken> thing'))
  await expect.poll(() => page.evaluate(() => window.programStatus()), { timeout: 3000 }).toBe('error')
  const error = await page.evaluate(() => window.programError())
  assert.equal(error.code, 'reader_failed')
  assert.match(error.message, /reading of this prompt/)
})
