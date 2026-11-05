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

async function fixture(t, { chat = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/api/**', route => route.fulfill({ json: [] }))
  if (chat) {
    await page.route('**/api/markers', route => route.fulfill({ json: [
      { id: 1, name: 'Keep', color: '#ffffff', icon_svg: '<svg></svg>' },
    ] }))
  }
  await page.route('http://slideshow-keyboard.test/', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://slideshow-keyboard.test/')
  if (chat) await page.evaluate(() => { window.slideshowChatTest = true })
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

test('a completed chat video retains its info and marker strip while its page reloads', async t => {
  const page = await fixture(t, { chat: true })
  const video = page.locator('video').first()
  const panel = page.getByTestId('media-info-panel')
  const marker = page.locator('.slideshow-control-bar').getByTitle('Add Keep', { exact: true })
  await expect(video).toHaveAttribute('src', /finished-video/)
  await expect(panel.getByRole('button', { name: 'More actions', exact: true }).first()).toBeVisible()
  await expect(marker).toBeVisible()
  await page.evaluate(() => window.slideshowKeys.refreshChat())
  // Flush the collection watcher while the replacement page remains unresolved.
  await expect(page.locator('.scroll-container [title="Loading..."]').first()).toBeAttached()
  await expect(video).toHaveAttribute('src', /finished-video/)
  await expect(panel.getByRole('button', { name: 'More actions', exact: true }).first()).toBeVisible()
  await expect(marker).toBeVisible()
  await page.evaluate(() => window.slideshowKeys.finishRefresh())
  await expect(page.locator('.scroll-container [title="Loading..."]')).toHaveCount(0)
  await expect(marker).toBeVisible()
})

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
