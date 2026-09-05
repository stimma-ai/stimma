import assert from 'node:assert/strict'
import test from 'node:test'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'

// Exercise the actual SFC without a running app or backend. Only HTTP media
// responses are fixtures; Vue rendering, transport and ImageDecoder are real.
test('slideshow selects moves/directions, scrubs merged holds and honors once', async () => {
  const built = await build({
    configFile: false,
    plugins: [vue()],
    logLevel: 'error',
    define: { 'process.env.NODE_ENV': JSON.stringify('production'), __STIMMA_DISTRIBUTION__: JSON.stringify('dev'), __STIMMA_COMMIT__: JSON.stringify('test') },
    build: {
      write: false, minify: false,
      lib: { entry: 'tests/fixtures/spritePlayer.js', name: 'SpritePlayerTest', formats: ['iife'] },
    },
  })
  const output = (Array.isArray(built) ? built[0] : built).output
  const bundle = output.find(item => item.type === 'chunk').code
  const css = output.filter(item => item.fileName.endsWith('.css')).map(item => item.source).join('\n')
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 900, height: 600 } })
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    // Two encoded frames: red held for 200ms, then blue for 100ms.
    const webp = Buffer.from('UklGRoQAAABXRUJQVlA4WAoAAAACAAAABwAABwAAQU5JTQYAAAAAAAAAAABBTk1GKAAAAAAAAAAAAAcAAAcAAMgAAAJWUDhMDwAAAC8HwAEABxD9j/4HIqL/AQBBTk1GKAAAAAAAAAAAAAcAAAcAAGQAAABWUDhMDwAAAC8HwAEABxDR//4HIqL/AQA=', 'base64')
    const animation = (name, direction, loop) => ({
      name, direction, loop, fps: 10, loop_start: 0, loop_end: 2,
      frame_count: 3, frames: [{}, {}, {}],
      animation: { resolved: { media_id: 2 }, frame_indices: [0, 0, 1] },
    })
    const doc = { title: 'Test sprite', animations: [
      animation('idle', 'east', 'loop'),
      animation('idle', 'west', 'pingpong'),
      animation('death', 'east', 'once'),
    ] }
    await page.route('http://localhost/**', route => {
      const url = new URL(route.request().url())
      if (url.pathname === '/api/media/1/content') return route.fulfill({ json: doc })
      if (url.pathname.endsWith('/file')) return route.fulfill({ contentType: 'image/webp', body: webp })
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app" style="width:900px;height:600px"></div>' })
      return route.fulfill({ json: {} })
    })
    await page.goto('http://localhost/')
    await page.addStyleTag({ content: css })
    await page.addScriptTag({ content: bundle })
    const canvas = page.locator('canvas')
    try {
      await canvas.waitFor({ timeout: 5000 })
    } catch (error) {
      assert.fail(`${error.message}; page errors: ${errors.join('; ')}; body: ${await page.locator('body').innerText()}`)
    }
    await page.waitForFunction(() => document.querySelector('canvas')?.getBoundingClientRect().width >= 400)
    if (process.env.SPRITE_TEST_SCREENSHOT) {
      await page.screenshot({ path: process.env.SPRITE_TEST_SCREENSHOT })
    }
    const pixel = () => canvas.evaluate(el => [...el.getContext('2d').getImageData(0, 0, 1, 1).data])
    const next = page.getByTitle('Next frame', { exact: true })
    assert.deepEqual(await pixel(), [255, 0, 0, 255])
    await next.click()
    assert.deepEqual(await pixel(), [255, 0, 0, 255])
    await next.click()
    assert.deepEqual(await pixel(), [0, 0, 255, 255])
    // Both move and direction selectors must be reachable in overlay mode.
    await page.getByRole('button', { name: 'west', exact: true }).click()
    await page.getByText('idle · west', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'death', exact: true }).click()
    await page.getByText('death · east', { exact: true }).waitFor()
    await next.waitFor({ state: 'visible' })
    await page.waitForFunction(() => !document.querySelector('[title="Next frame"]').disabled)
    assert.ok(!(await page.getByTitle('Toggle loop').getAttribute('class')).includes('!text-live'))
    await page.getByTitle('Play (space)', { exact: true }).click()
    await page.getByTitle('Pause (space)', { exact: true }).waitFor()
    await page.getByTitle('Play (space)', { exact: true }).waitFor()
    assert.deepEqual(await pixel(), [0, 0, 255, 255])
    assert.deepEqual(errors, [])
  } finally {
    await browser.close()
  }
})
