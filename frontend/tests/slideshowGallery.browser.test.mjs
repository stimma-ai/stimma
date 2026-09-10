import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium, expect } from '@playwright/test'
const result = await build({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), logLevel: 'silent', plugins: [vue()],
  define: { 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/slideshowGallery.ts', import.meta.url)), formats: ['iife'], name: 'GalleryTest',
  } },
})
const output = (Array.isArray(result) ? result : [result]).flatMap(r => r.output)
async function fixture(t, width = 390, reducedMotion = 'no-preference') {
  const browser = await chromium.launch(); t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height: 844 }, hasTouch: true, reducedMotion })
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('http://gallery.test/**', r => r.fulfill({ contentType: 'text/html', body: '<html class="dark"><body style="margin:0"><div id="app"></div></body></html>' }))
  await page.goto('http://gallery.test/')
  for (const asset of output.filter(x => x.type === 'asset' && x.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(x => x.type === 'chunk').code })
  return page
}
async function centered(page, index) {
  await expect.poll(() => page.evaluate(index => {
    const el = document.querySelector(`[data-index="${index}"]`)?.parentElement
    if (!el) return 9999
    const item = el.getBoundingClientRect(), container = document.querySelector('.scroll-container').getBoundingClientRect()
    return Math.abs(item.x + item.width / 2 - container.x - container.width / 2)
  }, index)).toBeLessThan(2)
}
test('four markers fit at 320px; overflow is searchable, toggleable and dismissible', async t => {
  const page = await fixture(t, 320)
  assert.equal(await page.getByRole('button', { name: /^Marker / }).count(), 4)
  for (const b of await page.getByRole('button', { name: /^Marker / }).all()) {
    const box = await b.boundingBox(); assert.ok(box.width >= 44 && box.height >= 44)
  }
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.evaluate(() => window.galleryTest.markers(24))
  await page.getByRole('button', { name: '21 more markers' }).tap()
  await page.getByRole('searchbox', { name: 'Find marker' }).fill('Marker 23')
  await page.getByRole('button', { name: 'Marker 23', exact: true }).tap()
  await expect(page.getByRole('button', { name: 'Marker 23', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('searchbox')).toHaveCount(0)
  await page.getByRole('button', { name: '21 more markers' }).tap()
  await page.mouse.click(10, 10)
  await expect(page.getByRole('searchbox')).toHaveCount(0)
})
test('filmstrip animates to selection, centers both edges, and stays virtualized', async t => {
  const page = await fixture(t)
  await centered(page, 0)
  await page.evaluate(() => window.galleryTest.select(8))
  await expect.poll(() => page.locator('.scroll-container').evaluate(el => el.scrollLeft)).toBeGreaterThan(0)
  const intermediate = await page.locator('.scroll-container').evaluate(el => el.scrollLeft)
  assert.ok(intermediate < 8 * 54, 'scroll has intermediate animation positions')
  await centered(page, 8)
  await page.evaluate(() => window.galleryTest.select(999))
  await centered(page, 999)
  assert.ok(await page.locator('[data-index]').count() < 40)
  await page.setViewportSize({ width: 320, height: 844 })
  await centered(page, 999)
})
test('slow loads cannot delay navigation; reduced motion centers immediately', async t => {
  const page = await fixture(t, 390, 'reduce')
  await centered(page, 0)
  await page.evaluate(() => { window.galleryTest.pending(); window.galleryTest.select(100) })
  await centered(page, 100)
  await page.evaluate(() => { window.galleryTest.select(400); window.galleryTest.select(3) })
  await centered(page, 3)
})
