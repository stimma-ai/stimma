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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/escapeLayers.ts', import.meta.url)), name: 'EscapeLayersTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('http://escape-layers.test/**', route => route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app"></div></body></html>' }))
  await page.goto('http://escape-layers.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

test('Escape dismisses a dropdown before its dialog and consumes the event', async t => {
  const page = await fixture(t)
  await page.getByRole('button', { name: 'Alpha' }).click()
  await expect(page.getByRole('listbox')).toBeVisible()
  await page.evaluate(() => {
    window.escaped = false
    window.addEventListener('keydown', event => { if (event.key === 'Escape') window.escaped = true })
  })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(page.locator('[data-test-parent]')).toBeVisible()
  assert.equal(await page.evaluate(() => window.escaped), false)
  await page.getByRole('textbox', { name: 'Dialog field' }).focus()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-test-parent]')).toHaveCount(0)
  assert.equal(await page.evaluate(() => window.escaped), false)
  assert.equal(await page.evaluate(() => window.escapeLayers.hasLayer()), false, 'a cached hidden layer cannot block shortcuts')
})

test('Escape follows visible z-order rather than modal DOM or listener order', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.escapeLayers.sheet())
  await expect(page.locator('[data-test-sheet]')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-test-sheet]')).toHaveCount(0)
  await expect(page.locator('[data-test-parent]')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-test-parent]')).toHaveCount(0)
})

test('a menu inside a lower stacking context cannot steal Escape from a dialog', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.escapeLayers.scopedMenu())
  await expect(page.locator('[data-test-scoped-menu]')).toBeAttached()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-test-parent]')).toHaveCount(0)
  await expect(page.locator('[data-test-scoped-menu]')).toBeVisible()
})

test('a nested confirmation closes without dismissing generation details underneath', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.escapeLayers.details())
  await expect(page.getByText('Generation details', { exact: true })).toBeVisible()
  await page.evaluate(() => window.escapeLayers.confirm())
  await expect(page.locator('[data-test-confirm]')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-test-confirm]')).toHaveCount(0)
  await expect(page.getByText('Generation details', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByText('Generation details', { exact: true })).toHaveCount(0)
  await expect(page.locator('[data-test-parent]')).toBeVisible()
})

test('Escape retains cancellation of an active AI selection request', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.escapeLayers.aiSelection())
  await expect(page.locator('[data-modal-layer]')).toHaveCount(0)
  await page.keyboard.press('Escape')
  assert.equal(await page.evaluate(() => window.escapeLayers.cancellations()), 1)
})

test('a sheet dismisses before Escape can cancel the AI selection underneath', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.escapeLayers.aiSelection())
  await expect(page.locator('[data-modal-layer]')).toHaveCount(0)
  await page.evaluate(() => window.escapeLayers.sheet())
  await expect(page.locator('[data-test-sheet]')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-test-sheet]')).toHaveCount(0)
  assert.equal(await page.evaluate(() => window.escapeLayers.cancellations()), 0)
  await page.keyboard.press('Escape')
  assert.equal(await page.evaluate(() => window.escapeLayers.cancellations()), 1)
})
