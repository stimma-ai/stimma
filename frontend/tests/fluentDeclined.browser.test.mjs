import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// A prompt the chat model declined: the box switches to Direct after the run, says why in
// plain words, and switching back to Fluent shows the same notice (no silent retry).
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/fluentDeclined.ts', import.meta.url)), name: 'FluentDeclinedTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))

const NOTICE = 'Your chat model declined this prompt, so it’s being sent as written.'

async function open(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html class="dark"><body><div id="app"></div></body></html>' }))
  await page.goto('http://fluent-declined.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  const chip = page.locator('[data-fluent-chip]')
  await chip.waitFor()
  t.after(() => assert.deepEqual(errors, []))
  return { page, chip }
}

test('a declined prompt runs as written, then the box switches to Direct and says why', async t => {
  const { page, chip } = await open(t)
  await expect(chip).toHaveText(/Fluent · as written/)
  await page.evaluate(() => window.run())
  await expect(chip).toHaveText(/^\s*Direct/)
  await expect(page.locator('[data-toast="info"]')).toHaveText(NOTICE)
  const state = await page.evaluate(() => window.state())
  assert.equal(state.direct, true)
  assert.deepEqual(state.autoImprove, { enabled: true, level: 'expand' })  // Detail level kept for coming back
  // Runs in Direct say nothing more.
  await page.evaluate(() => window.run())
  await expect(page.locator('[data-toast]')).toHaveCount(1)
  assert.deepEqual(await page.evaluate(() => window.runs), ['fluent', 'direct'])
})

test('back in Fluent, the menu says the same and offers no Try again; the next run switches again', async t => {
  const { page, chip } = await open(t)
  await page.evaluate(() => window.run())
  await page.evaluate(() => window.clearToasts())
  await expect(page.locator('[data-toast]')).toHaveCount(0)
  await chip.click()
  const menu = page.locator('[data-fluent-menu]')
  await menu.getByRole('radio', { name: 'Fluent' }).click()
  await expect(chip).toHaveText(/Fluent · as written/)
  await expect(menu.getByText('Your chat model declined this prompt')).toBeVisible()
  await expect(menu.getByText('It’s sent as written.')).toBeVisible()
  await expect(menu.getByRole('button', { name: 'Try again' })).toHaveCount(0)
  for (const word of ['prepare', 'writer', 'program']) {
    assert.doesNotMatch(await menu.innerText(), new RegExp(word, 'i'))
  }
  assert.equal(await page.evaluate(() => window.prepared || 0), 0)  // nothing asked the chat model again
  await page.keyboard.press('Escape')
  await page.evaluate(() => window.run())
  await expect(chip).toHaveText(/^\s*Direct/)
  await expect(page.locator('[data-toast="info"]').last()).toHaveText(NOTICE)
})
