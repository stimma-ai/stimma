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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/slideshowKeyboard.ts', import.meta.url)), name: 'SlideshowKeyboardTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/api/**', route => route.fulfill({ json: [] }))
  await page.route('http://slideshow-keyboard.test/', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://slideshow-keyboard.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

test('Slideshow owns navigation, playback and viewer keys while a Modal blocks both viewer and grid', async t => {
  const page = await fixture(t)
  const viewer = page.locator('[data-escape-layer][data-drop-zone]')
  await expect(viewer).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
  await page.keyboard.press('ArrowLeft')
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await page.keyboard.press('Space')
  await expect(page.getByTitle('Pause (space)', { exact: true })).toBeVisible()
  await page.keyboard.press('Space')
  await expect(page.getByTitle('Play slideshow (space)', { exact: true })).toBeVisible()
  await page.keyboard.press('f')
  await expect(page.locator('body')).toHaveClass(/slideshow-focus-mode/)
  await page.keyboard.press('f')
  await expect(page.locator('body')).not.toHaveClass(/slideshow-focus-mode/)
  assert.deepEqual(await page.evaluate(() => window.slideshowKeys.grid), [])
  await page.evaluate(() => window.slideshowKeys.modal())
  await expect(page.getByRole('dialog')).toBeFocused()
  for (const key of ['ArrowRight', 'Space', 'f', 'Delete', 'Control+a']) await page.keyboard.press(key)
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await expect(page.getByTitle('Play slideshow (space)', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toHaveClass(/slideshow-focus-mode/)
  assert.deepEqual(await page.evaluate(() => window.slideshowKeys.grid), [])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
})
