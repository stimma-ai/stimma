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

async function open(t, choiceId) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html class="dark"><body><div id="app"></div></body></html>' }))
  await page.goto('http://program-card.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.evaluate(id => window.openChoice(id), choiceId)
  const card = page.locator('[data-program-card]')
  await card.waitFor()
  t.after(() => assert.deepEqual(errors, []))
  const option = text => card.locator('[data-option]').filter({ hasText: new RegExp(`^${text}$`) })
  const options = () => card.locator('[data-option]').allTextContents().then(all => all.map(s => s.trim()))
  const group = tier => card.locator(`[data-group="${tier}"]`)
  return { page, card, option, options, group }
}

test('a short pick keeps the plain list: no search', async t => {
  const { card, options } = await open(t, 'mood')
  await expect(card.getByPlaceholder('Search options')).toHaveCount(0)
  assert.deepEqual(await options(), ['calm', 'tense', 'joyful', 'wistful'])
  await expect(card.getByText('More like these')).toBeVisible()
  await expect(card.getByText('New set')).toBeVisible()
})

test('a long unbound pick filters as you type, ticked values first whatever the filter', async t => {
  const { page, card, option, options } = await open(t, 'color')
  await expect(card.getByText(/ list$/)).toHaveCount(0)
  await option('shade 12').click()
  const search = card.getByPlaceholder('Search options')
  await search.fill('shade 1')
  assert.deepEqual(await options(), ['shade 12', 'shade 1', 'shade 10', 'shade 11', 'shade 13', 'shade 14', 'shade 15'])
  await search.fill('shade 7')
  assert.deepEqual(await options(), ['shade 12', 'shade 7'])
  await search.fill('nothing like it')
  await expect(card.getByText('No matches')).toBeVisible()
  await card.getByText('Add “nothing like it”').click()
  await expect.poll(() => page.evaluate(() => window.state().edits.color)).toEqual({ add: ['nothing like it'] })
  // Escape clears the search and stops there; the next one belongs to the card.
  await search.fill('shade')
  await search.press('Escape')
  await expect(search).toHaveValue('')
  assert.equal(await page.evaluate(() => window.escapes()), 0)
})

test('a list-drawn pick groups usual to rare; search opens the groups with hits', async t => {
  const { page, card, option, options, group } = await open(t, 'expression')
  await expect(card.getByText('Expression list')).toBeVisible()
  await expect(group('typical')).toHaveAttribute('aria-expanded', 'true')
  for (const [tier, text] of [['plausible', 'Less usual8'], ['unusual', 'Rare6'], ['generated', 'More ideas5']]) {
    await expect(group(tier)).toHaveAttribute('aria-expanded', 'false')
    await expect(group(tier)).toHaveText(text)
  }
  assert.equal((await options()).length, 10)
  await group('unusual').click()
  await option('odd squint 2').click()
  await expect.poll(() => page.evaluate(() => window.state().pins.expression)).toEqual(['odd squint 2'])
  await group('unusual').click()
  // The ticked value leads, outside its group.
  assert.equal((await options())[0], 'odd squint 2')
  await card.getByPlaceholder('Search options').fill('grimace 3')
  await expect(group('generated')).toHaveAttribute('aria-expanded', 'true')
  await expect(group('typical')).toHaveCount(0)
  assert.deepEqual(await options(), ['odd squint 2', 'new grimace 3'])
  // Delete is remembered per pick, as before.
  await option('new grimace 3').hover()
  await option('new grimace 3').getByLabel('Delete new grimace 3').click()
  await expect.poll(() => page.evaluate(() => window.state().edits.expression)).toEqual({ add: [], remove: ['new grimace 3'] })
})

test('an open list offers More like these but not a whole new set', async t => {
  const { card } = await open(t, 'expression')
  await expect(card.getByText('More like these')).toBeVisible()
  await expect(card.getByText('New set')).toHaveCount(0)
})

test('a closed list asks no model for options, and still takes your own', async t => {
  const { page, card } = await open(t, 'ethnicity')
  await expect(card.getByText('More like these')).toHaveCount(0)
  await expect(card.getByText('New set')).toHaveCount(0)
  const own = card.getByPlaceholder('Add your own…')
  await own.fill('my own heritage')
  await own.press('Enter')
  await expect.poll(() => page.evaluate(() => window.state().edits.ethnicity)).toEqual({ add: ['my own heritage'] })
  await expect(card.locator('[data-option="my own heritage"]')).toBeVisible()
})

test('shift-click ticks a range, and unticks one from a ticked option', async t => {
  const { page, option } = await open(t, 'mood')
  const pins = () => page.evaluate(() => window.state().pins.mood)
  await option('tense').click()
  await option('wistful').click({ modifiers: ['Shift'] })
  await expect.poll(pins).toEqual(['tense', 'joyful', 'wistful'])
  await option('calm').click({ modifiers: ['Control'] })
  await expect.poll(pins).toEqual(['calm', 'tense', 'joyful', 'wistful'])
  await option('joyful').click({ modifiers: ['Shift'] })
  await expect.poll(pins).toEqual(['wistful'])
})

test('shift-click ranges follow the list as it reads before anything floats up', async t => {
  const { page, option } = await open(t, 'color')
  await option('shade 3').click()
  await option('shade 6').click({ modifiers: ['Shift'] })
  await expect.poll(() => page.evaluate(() => window.state().pins.color)).toEqual(['shade 3', 'shade 4', 'shade 5', 'shade 6'])
})

test('a shift-click range starts from a ticked option the search would hide', async t => {
  const { page, card, option } = await open(t, 'color')
  await option('shade 3').click()
  await card.getByPlaceholder('Search options').fill('shade 1')
  await option('shade 15').click({ modifiers: ['Shift'] })
  await expect.poll(() => page.evaluate(() => window.state().pins.color)).toEqual(['shade 3', 'shade 10', 'shade 11', 'shade 12', 'shade 13', 'shade 14', 'shade 15'])
})


test('friends have visible wrapping sections with their own colors and direct pickers', async t => {
  const { page } = await open(t, 'mood')
  await page.setViewportSize({ width: 320, height: 900 })
  // Close the initial picker before exercising the property sections.
  await page.evaluate(() => window.openChoice(null))
  const sections = page.locator('[data-program-section]')
  assert.deepEqual(await sections.evaluateAll(nodes => nodes.map(n => n.getAttribute('aria-label'))), ['General', 'Friend 1', 'Friend 2'])
  for (const index of [1, 2]) {
    const section = page.getByRole('region', { name: `Friend ${index}`, exact: true })
    await expect(section.getByRole('heading', { name: `Friend ${index}`, exact: true })).toBeVisible()
    await expect(section.getByRole('button', { name: 'Hair color', exact: true })).toBeVisible()
    const colors = section.getByRole('button', { name: 'Colors', exact: true })
    await expect(colors).toBeVisible()
    const hairBox = await section.getByRole('button', { name: 'Age', exact: true }).boundingBox()
    const colorBox = await colors.boundingBox()
    assert.ok(colorBox.y > hairBox.y, 'controls wrap within the friend section')
    await colors.click()
    const card = page.locator('[data-program-card]')
    await expect(card.getByText(`Friend ${index} · Colors`, { exact: true })).toBeVisible()
    await card.locator('[data-option="navy and white"]').click()
    await expect.poll(() => page.evaluate(i => window.state().pins[`friends[${i}].outfit.colours`], index)).toEqual(['navy and white'])
    await page.evaluate(() => window.openChoice(null))
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.equal(overflow, false)
})
