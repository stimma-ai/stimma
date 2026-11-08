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
for (const viewport of ['wide', 'compact']) test(`the ${viewport} results rail scrolls to the result the slideshow left off on`, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: viewport === 'compact' ? { width: 390, height: 844 } : { width: 800, height: 600 } })
  page.setDefaultTimeout(5000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: `<html data-viewport="${viewport}"><body><div id="app"></div></body></html>` }))
  await page.goto('http://jobs-reveal.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.waitForSelector('[data-job-id="80"] .jobs-tile')
  // The rail's scroller: the desktop rail itself, or the phone's sideways strip.
  const scroller = viewport === 'compact' ? '.jobs-results' : '#rail'
  const offset = () => page.locator(scroller).evaluate(el => el.scrollTop + el.scrollLeft)
  const inView = id => page.evaluate(([id, scroller]) => {
    const tile = document.querySelector(`[data-job-id="${id}"] .jobs-tile`)
    if (!tile) return null
    const a = tile.getBoundingClientRect(), b = document.querySelector(scroller).getBoundingClientRect()
    return a.width > 0 && a.top >= b.top && a.bottom <= b.bottom && a.left >= b.left && a.right <= b.right
  }, [id, scroller])

  // Past the 30 tiles mounted up front: reveal mounts it, then scrolls to it.
  assert.equal(await inView(20), null)
  assert.equal(await page.evaluate(() => window.revealJob(20)), true)
  assert.equal(await inView(20), true)
  assert.ok(await offset() > 0)

  // A tile already on screen stays put.
  const before = await offset()
  const neighbour = await page.evaluate(scroller => {
    const view = document.querySelector(scroller).getBoundingClientRect()
    return [...document.querySelectorAll('[data-job-id]')].map(el => [Number(el.dataset.jobId), el.querySelector('.jobs-tile').getBoundingClientRect()])
      .find(([, box]) => box.width > 0 && box.top >= view.top && box.bottom <= view.bottom && box.left >= view.left && box.right <= view.right)[0]
  }, scroller)
  assert.equal(await page.evaluate(id => window.revealJob(id), neighbour), true)
  assert.equal(await offset(), before)

  // Back to the newest.
  assert.equal(await page.evaluate(() => window.revealJob(80)), true)
  assert.equal(await inView(80), true)
  assert.equal(await page.evaluate(() => window.revealJob(9999)), false)
  assert.deepEqual(errors, [])
})
