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
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/jobsReveal.ts', import.meta.url)), name: 'JobsRevealTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
test('the results rail scrolls to the result the slideshow left off on', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } })
  page.setDefaultTimeout(5000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app"></div></body></html>' }))
  await page.goto('http://jobs-reveal.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.waitForSelector('[data-job-id="80"]')
  const inView = id => page.evaluate(id => {
    const tile = document.querySelector(`[data-job-id="${id}"]`), rail = document.querySelector('#rail')
    if (!tile) return null
    const a = tile.getBoundingClientRect(), b = rail.getBoundingClientRect()
    return a.top >= b.top && a.bottom <= b.bottom
  }, id)

  // Past the 30 tiles mounted up front: reveal mounts it, then scrolls to it.
  assert.equal(await inView(20), null)
  assert.equal(await page.evaluate(() => window.revealJob(20)), true)
  assert.equal(await inView(20), true)
  assert.ok(await page.locator('#rail').evaluate(el => el.scrollTop) > 0)

  // A tile already on screen stays put.
  const before = await page.locator('#rail').evaluate(el => el.scrollTop)
  const neighbour = await page.evaluate(() => {
    const rail = document.querySelector('#rail').getBoundingClientRect()
    return [...document.querySelectorAll('[data-job-id]')].map(el => [Number(el.dataset.jobId), el.getBoundingClientRect()])
      .find(([, box]) => box.top >= rail.top && box.bottom <= rail.bottom)[0]
  })
  assert.equal(await page.evaluate(id => window.revealJob(id), neighbour), true)
  assert.equal(await page.locator('#rail').evaluate(el => el.scrollTop), before)

  // Back to the newest.
  assert.equal(await page.evaluate(() => window.revealJob(80)), true)
  assert.equal(await inView(80), true)
  assert.equal(await page.evaluate(() => window.revealJob(9999)), false)
  assert.deepEqual(errors, [])
})
