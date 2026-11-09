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

async function fixture(t, { chat = false, nav = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/api/**', route => route.fulfill({ json: [] }))
  if (chat || nav) {
    await page.route('**/api/markers', route => route.fulfill({ json: [
      { id: 1, name: 'Keep', color: '#ffffff', icon_svg: '<svg></svg>' },
    ] }))
  }
  await page.route('http://slideshow-keyboard.test/', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://slideshow-keyboard.test/')
  if (chat) await page.evaluate(() => { window.slideshowChatTest = true })
  if (nav) await page.evaluate(() => { window.slideshowNavTest = true })
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

test('after stepping to an image that is still loading, nothing acts on the one left behind', async t => {
  const page = await fixture(t, { nav: true })
  const deletes = []
  await page.route('**/api/**', route => {
    if (route.request().method() === 'DELETE' || /trash|delete/.test(route.request().url())) deletes.push(route.request().url())
    return route.fallback()
  })
  const marker = page.locator('.slideshow-control-bar').getByTitle('Add Keep', { exact: true })
  const image = page.locator('img[src*="still-31"]').first()
  await expect(image).toBeVisible()
  await expect(marker).toBeVisible()
  // Reload the chat's page and hold it: the first image stays up with its controls.
  await page.evaluate(() => window.slideshowKeys.refreshChat())
  await expect(page.locator('.scroll-container [title="Loading..."]').first()).toBeAttached()
  await expect(marker).toBeVisible()
  // Step on while the page is still out: the old picture stays up, its actions do not.
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
  await expect(image).toBeVisible()
  await expect(marker).toHaveCount(0)
  await page.keyboard.press('Delete')
  await page.keyboard.press('Backspace')
  assert.deepEqual(deletes, [])
  await page.evaluate(() => window.slideshowKeys.finishRefresh())
  await expect(page.locator('img[src*="still-32"]').first()).toBeVisible()
  await expect(marker).toBeVisible()
})

test('chorded keys go to the browser, and Backspace trashes like Delete', async t => {
  const page = await fixture(t, { nav: true })
  const deletes = []
  await page.route('**/api/**', route => {
    if (route.request().method() === 'DELETE' || /trash|delete/.test(route.request().url())) deletes.push(route.request().url())
    return route.fallback()
  })
  await expect(page.locator('img[src*="still-31"]').first()).toBeVisible()
  for (const key of ['Control+d', 'Meta+d', 'Alt+d', 'Meta+ArrowRight', 'Control+f', 'Meta+f', 'Meta+i', 'Meta+a']) await page.keyboard.press(key)
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await expect(page.locator('body')).not.toHaveClass(/slideshow-focus-mode/)
  await expect(page.getByTestId('media-info-panel')).toBeVisible()
  await page.keyboard.press('d')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
  await expect(page.locator('img[src*="still-32"]').first()).toBeVisible()
  await page.keyboard.press('Backspace')
  await expect.poll(() => deletes.length).toBe(1)
  assert.match(deletes[0], /32/)
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
