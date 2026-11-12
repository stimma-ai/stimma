import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The prompt menu's Fluent tab: each detail level says, in a line, how much it adds; the
// old writer's controls are gone.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/fluentMenu.ts', import.meta.url)), name: 'FluentMenuTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

async function open(t, pageOptions = { viewport: { width: 700, height: 800 } }) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage(pageOptions)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html data-theme="dark"><head><meta name="viewport" content="width=device-width"></head><body><div id="app"></div></body></html>' }))
  await page.goto('http://fluent-menu.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  t.after(() => assert.deepEqual(errors, []))
  await page.locator('[data-fluent-chip]').click()
  const menu = page.locator('[data-fluent-menu]')
  await expect(menu).toBeVisible()
  return { page, menu }
}

test('each detail level says how much it adds, in plain words', async t => {
  const { page, menu } = await open(t)
  const line = menu.locator('[data-detail-line]')
  await expect(line).toHaveText('Adds a little: a few sentences, or a short list of tags.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/fluent-menu-medium.png` })
  await expect(menu).toContainText('then writes its prompt the way Krea 2 reads best')
  await menu.getByRole('radio', { name: 'High' }).click()
  assert.equal(await page.evaluate(() => window.level()), 'expand')
  await expect(line).toHaveText('Adds a lot: a full paragraph, or a long list of tags.')
  await menu.getByRole('radio', { name: 'Yours' }).click()
  assert.equal(await page.evaluate(() => window.level()), 'off')
  await expect(line).toHaveText('Your words as written, nothing added.')
  await expect(menu).toContainText('keeping your wording')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/fluent-menu-yours.png` })
  // Nothing reads LoRA notes at Yours; trigger words still go in.
  await expect(menu.getByText('LoRA notes')).toHaveCount(0)
  await expect(menu.getByText('LoRA trigger words')).toBeVisible()
  // The old writer's retake is gone, and no copy explains mechanics.
  await expect(menu.getByText(/Try different/)).toHaveCount(0)
  const text = await menu.innerText()
  assert.doesNotMatch(text, /wildcards? and follows|expands your prompt|—/)
})

test('on a phone the menu reads the same', async t => {
  const { menu } = await open(t, { viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true })
  await expect(menu.locator('[data-detail-line]')).toBeVisible()
  const box = await menu.boundingBox()
  assert.ok(box && box.x >= 0 && box.x + box.width <= 390, `menu at ${JSON.stringify(box)}`)
})
