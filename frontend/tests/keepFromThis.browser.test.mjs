import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Keep from this on a result: what one image drew, as a few lines, each ticked when the
// choices hold exactly that image's value. Same fixture as the chooser's: the real composable
// and pills against a stand-in server.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/promptProgramCard.ts', import.meta.url)), name: 'KeepFromThisTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

// What generation records for one image (backend routes/generation.py, prompt_program).
const RUN = {
  key: 'k3', version: 'slots-1', prompt: 'dorm room with a 24-year-old Korean man…',
  draws: [
    { id: 'young_man.age', value: '24-year-old', kind: 'pick', label: 'Age' },
    { id: 'young_man.descent', value: 'Korean', kind: 'pick', label: 'Descent' },
    { id: 'young_man.build', value: 'stocky', kind: 'pick', label: 'Build' },
    { id: 'young_man.hair', value: 'buzz cut', kind: 'pick', label: 'Hair' },
    { id: 'young_man.outfit', value: 'a navy flannel shirt and gray jeans', template: 'a {main} flannel shirt and {neutral} jeans', kind: 'pick', label: 'Outfit' },
    { id: 'young_man.outfit.colors', value: 'navy, white and gray', kind: 'pick', label: 'Colors' },
    { id: 'pet', value: 'old basset hound', kind: 'pick', label: 'Pet' },
    { id: 'light', value: 'a string of warm fairy lights tracing the bed frame', kind: 'pick', label: 'Light' },
    { id: 'list1', value: 'autumn', kind: 'pick', label: 'Season', source: 'list' },
  ],
}

async function open(t, pageOptions = { viewport: { width: 900, height: 900 } }) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage(pageOptions)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html data-theme="dark"><head><meta name="viewport" content="width=device-width"></head><body><div id="app"></div></body></html>' }))
  await page.goto('http://keep-from-this.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  t.after(() => assert.deepEqual(errors, []))
  await expect.poll(() => page.evaluate(() => window.programStatus())).toBe('ready')
  const card = page.locator('[data-keep-card]')
  const line = key => card.locator(`[data-keep="${key}"]`)
  const state = () => page.evaluate(() => window.state())
  return { page, card, line, state, row: page.locator('[data-program-choices]') }
}

test('an image’s lines: a person’s look, their outfit, then each other slot and list, short', async t => {
  const { page, card } = await open(t)
  await page.evaluate(run => window.keep(run), RUN)
  await expect(card).toBeVisible()
  const lines = await card.locator('[data-keep]').evaluateAll(rs => rs.map(r => r.innerText.replace(/\s+/g, ' ').trim()))
  assert.deepEqual(lines, [
    'Look 24-year-old, Korean, stocky, buzz cut',
    'Outfit flannel and jeans',
    'Pet basset hound',
    'Light fairy lights',
    'Season autumn',
  ])
  await expect(card.getByText('Young man')).toBeVisible()
  await expect(card.locator('[data-keep-swatches] span')).toHaveCount(3)
  // Nothing promises the same person.
  assert.doesNotMatch(await card.innerText(), /same|him|her\b|this person|keep (him|her)/i)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/keep-from-this.png` })
})

test('a tick sets exactly what the image drew, as if chosen; unticking puts it back', async t => {
  const { page, line, state, row } = await open(t)
  await page.evaluate(run => window.keep(run), RUN)
  await line('young_man#look').click()
  await expect.poll(state).toEqual({
    'young_man.age': { values: ['24-year-old'] }, 'young_man.descent': { values: ['Korean'] },
    'young_man.build': { values: ['stocky'] }, 'young_man.hair': { values: ['buzz cut'] },
  })
  await expect(line('young_man#look')).toHaveAttribute('aria-checked', 'true')
  // Four details chosen fold into the person's pill, like any choosing.
  await expect(row.locator('[data-choice="young_man"]')).toContainText('24-year-old')
  await line('young_man.outfit').click()
  await expect.poll(async () => (await state())['young_man.outfit']).toEqual({ values: ['a {main} flannel shirt and {neutral} jeans'] })
  await expect.poll(async () => (await state())['young_man.outfit.colors']).toEqual({ values: ['navy, white and gray'] })
  await line('young_man#look').click()
  await expect(line('young_man#look')).toHaveAttribute('aria-checked', 'false')
  await expect.poll(async () => Object.keys(await state()).sort()).toEqual(['young_man.outfit', 'young_man.outfit.colors'])
})

test('a line is ticked when the choices already hold that value, from the chooser or anywhere', async t => {
  const { page, line } = await open(t)
  await page.evaluate(() => window.setState({ pet: { values: ['old basset hound'] }, light: { values: ['cool daylight entering through a tall window'] } }))
  await page.evaluate(run => window.keep(run), RUN)
  await expect(line('pet')).toHaveAttribute('aria-checked', 'true')
  await expect(line('light')).toHaveAttribute('aria-checked', 'false')
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-keep-card]')).toHaveCount(0)
})

test('an image the old writer made offers nothing to keep', async t => {
  const { page, card } = await open(t)
  await page.evaluate(run => window.keep({ ...run, version: undefined, mode: 'prose', elaborate: true }), RUN)
  await expect(card.locator('[data-keep]')).toHaveCount(0)
  await expect(card.locator('[data-keep-none]')).toBeVisible()
})
