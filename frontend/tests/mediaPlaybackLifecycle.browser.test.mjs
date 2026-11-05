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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/mediaPlaybackLifecycle.ts', import.meta.url)), name: 'MediaLifecycleTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

test('artifact and workspace media stop on close, navigation and replacement', { timeout: 20000 }, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    // Unsupported manifests exercise the real native fallback.
    if (path.includes('manifest')) return route.fulfill({ json: { mime_type: 'unsupported/test' } })
    if (path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://media-lifecycle.test/')
  // Model the media engine deterministically: lifecycle assertions must also
  // cover detached elements and late play events, without codec dependencies.
  await page.evaluate(() => {
    const playing = new WeakSet()
    Object.defineProperty(HTMLMediaElement.prototype, 'paused', { get() { return !playing.has(this) } })
    HTMLMediaElement.prototype.play = function () { playing.add(this); this.dispatchEvent(new Event('play')); return Promise.resolve() }
    HTMLMediaElement.prototype.pause = function () { playing.delete(this) }
    HTMLMediaElement.prototype.load = function () {}
  })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  for (const surface of ['artifact', 'video', 'audio']) {
    await page.evaluate(surface => { window.mediaLifecycle.surface.value = surface; window.mediaLifecycle.open.value = true }, surface)
    const media = page.locator('video,audio')
    await expect(media).toHaveCount(1)
    if (surface === 'artifact') await expect.poll(() => media.evaluate(el => el.paused)).toBe(false)
    if (surface === 'artifact') {
      await media.evaluate(el => { window.oldMedia = el })
      await page.evaluate(() => { window.mediaLifecycle.covered.value = true })
      await expect(media).toHaveCount(0)
      assert.equal(await page.evaluate(() => window.oldMedia.paused && !window.oldMedia.hasAttribute('src')), true)
      await page.evaluate(() => { window.mediaLifecycle.covered.value = false })
      await expect.poll(() => media.evaluate(el => el.paused)).toBe(false)
    }
    await media.evaluate(el => { window.oldMedia = el; return el.play() })
    await page.evaluate(() => { window.mediaLifecycle.active.value = false })
    await expect.poll(() => page.evaluate(() => window.oldMedia.paused)).toBe(true)
    await page.locator('[data-other-player]').evaluate(el => el.play())
    if (surface !== 'artifact') assert.equal(await page.evaluate(() => window.oldMedia.hasAttribute('src')), true)
    // A pending canplay/MSE callback must not revive a cached screen.
    await page.evaluate(() => window.oldMedia.play())
    assert.equal(await page.evaluate(() => window.oldMedia.paused), true)
    await page.evaluate(() => { window.mediaLifecycle.active.value = true })
    await expect(media).toHaveCount(1)
    await media.evaluate(el => el.play())
    assert.equal(await media.evaluate(el => !el.paused && el.hasAttribute('src')), true)
    await media.evaluate(el => { window.oldMedia = el; return el.play() })
    await page.evaluate(() => { window.mediaLifecycle.revisionId.value++ })
    await expect.poll(() => page.evaluate(() => window.oldMedia.paused && !window.oldMedia.hasAttribute('src'))).toBe(true)
    await media.evaluate(el => { window.oldMedia = el; return el.play() })
    await page.evaluate(() => { window.mediaLifecycle.open.value = false })
    await expect(media).toHaveCount(0)
    assert.equal(await page.evaluate(() => window.oldMedia.paused && !window.oldMedia.hasAttribute('src')), true)
  }
  assert.deepEqual(errors, [])
})
