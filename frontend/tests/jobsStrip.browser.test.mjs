import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium } from '@playwright/test'
import config from '../vite.config.js'
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/jobsStrip.ts', import.meta.url)), name: 'JobsStripTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
for (const [width, height] of [[390, 844], [752, 844], [752, 420]]) test(`mixed-aspect outputs fit at ${width}×${height}`, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height }, isMobile: true, hasTouch: true })
  page.setDefaultTimeout(5000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html data-viewport="compact"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div></body></html>' }))
  await page.goto('http://jobs-strip.test/?viewport=compact&pointer=coarse')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.waitForSelector('.jobs-tile')
  for (const railHeight of [60, 48, 80]) {
    await page.locator('#rail').evaluate((el, height) => { el.style.height = `${height}px` }, railHeight)
    const geometry = await page.evaluate(() => {
      const strip = document.querySelector('.jobs-results'), box = strip.getBoundingClientRect()
      return { height: box.height, scrollHeight: strip.scrollHeight, tiles: [...document.querySelectorAll('.jobs-tile')].map(el => {
        const rect = el.getBoundingClientRect(), ratio = getComputedStyle(el).aspectRatio.split('/').map(Number)
        return { height: rect.height, width: rect.width, top: rect.top - box.top, aspect: ratio[0] / (ratio[1] || 1) }
      }) }
    })
    assert.equal(geometry.tiles.length, 9)
    assert.equal(geometry.height, railHeight - 4)
    assert.equal(geometry.scrollHeight, geometry.height, 'no hidden vertical overflow')
    for (const tile of geometry.tiles) {
      assert.equal(tile.top, 0, 'items share one row')
      assert.equal(tile.height, geometry.height)
      assert.ok(Math.abs(tile.width / tile.height - tile.aspect) < 0.01, 'width follows aspect')
    }
  }
  // Desktop keeps its width-driven vertical rail.
  await page.evaluate(() => document.documentElement.dataset.viewport = 'wide')
  const desktop = await page.locator('.jobs-tile').evaluateAll(tiles => tiles.map(el => {
    const box = el.getBoundingClientRect(), ratio = getComputedStyle(el).aspectRatio.split('/').map(Number)
    return { width: box.width, height: box.height, aspect: ratio[0] / (ratio[1] || 1) }
  }))
  for (const tile of desktop) {
    assert.equal(tile.width, width - 4)
    assert.ok(Math.abs(tile.width / tile.height - tile.aspect) < 0.01)
  }
  assert.deepEqual(errors, [])
})
