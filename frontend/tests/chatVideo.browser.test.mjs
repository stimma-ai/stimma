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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatVideo.ts', import.meta.url)), name: 'ChatVideoTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

for (const phone of [false, true]) test(`chat video playback and toolbar (${phone ? 'touch' : 'mouse'})`, { timeout: 20000 }, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: phone ? { width: 390, height: 844 } : { width: 1280, height: 900 }, isMobile: phone, hasTouch: phone })
  let video
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div></body></html>' })
    if (path.endsWith('/file')) return route.fulfill({ contentType: 'video/webm', body: video })
    if (path.includes('thumbnail')) {
      const fit = new URL(route.request().url()).searchParams.get('mode') === 'fit'
      return route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="${fit ? 320 : 180}" height="180"><rect width="100%" height="180" fill="teal"/><rect width="20" height="180" fill="red"/><rect x="${fit ? 300 : 160}" width="20" height="180" fill="blue"/></svg>` })
    }
    if (path.includes('markers')) return route.fulfill({ json: [] })
    if (/\/media\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').at(-1)), file_format: path.endsWith('/1') ? 'webm' : 'png', width: 320, height: 180 } })
    return route.fulfill({ json: {} })
  })
  await page.goto(`http://chat-video.test/${phone ? '?viewport=compact&pointer=coarse' : ''}`)
  // Generate a real playable clip in the browser without a checked-in binary.
  video = Buffer.from(await page.evaluate(async () => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180
    const context = canvas.getContext('2d'); context.fillStyle = 'teal'; context.fillRect(0, 0, 320, 180)
    const stream = canvas.captureStream(10)
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' })
    const chunks = []
    const done = new Promise(resolve => { recorder.ondataavailable = e => chunks.push(e.data); recorder.onstop = resolve })
    const draw = setInterval(() => { context.fillStyle = `rgb(0, ${Math.floor(Math.random() * 150)}, 120)`; context.fillRect(0, 0, 320, 180) }, 40)
    recorder.start(); await new Promise(resolve => setTimeout(resolve, 2000)); recorder.stop(); await done; clearInterval(draw)
    stream.getTracks().forEach(track => track.stop())
    return [...new Uint8Array(await new Blob(chunks).arrayBuffer())]
  }))
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect(page.getByTestId('shown-video').locator('img')).toHaveAttribute('src', /mode=fit/)
  await expect(page.getByTestId('contained-video').locator('img')).toHaveAttribute('src', /mode=fit/)
  await expect(page.getByTestId('flow-video').locator('img')).toHaveAttribute('src', /mode=fit/)
  for (const id of ['covered-video', 'explicit-crop']) {
    assert.notEqual(new URL(await page.getByTestId(id).locator('img').getAttribute('src'), page.url()).searchParams.get('mode'), 'fit')
  }
  const hero = page.getByTestId('media-collection-hero')
  const play = hero.getByRole('button', { name: 'Play video', exact: true })
  await expect(play).toBeVisible()
  await expect(hero.locator('video')).toHaveCount(0)
  const poster = hero.locator('img').first()
  await expect(poster).toHaveAttribute('src', /mode=fit/)
  const surface = hero.locator('[data-video-surface]')
  const add = hero.getByRole('button', { name: 'Add to message' })
  await page.screenshot({ path: `/tmp/chat-video-${phone ? 'touch' : 'mouse'}.png` })
  assert.ok((await add.boundingBox()).y >= (await play.boundingBox()).y + (await play.boundingBox()).height - 1)
  if (!phone) {
    await play.hover()
    await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && v.muted && v.loop)).toBe(true)
    await page.mouse.move(1100, 850)
    await expect(hero.locator('video')).toHaveCount(0)
    await play.hover()
    await expect(hero.locator('video')).toHaveCount(1)
  }
  await play.click()
  await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && !v.muted && !v.loop)).toBe(true)
  await hero.getByRole('button', { name: 'Pause video' }).click()
  await expect.poll(() => hero.locator('video').evaluate(v => v.paused)).toBe(true)
  await play.focus(); await page.keyboard.press('Space')
  await expect(hero.getByRole('button', { name: 'Pause video' })).toBeVisible()
  await add.click()
  await expect(hero.getByRole('button', { name: 'In message' })).toBeVisible()
  assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [])
  const drag = await surface.evaluate(button => {
    const dataTransfer = new DataTransfer()
    button.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer }))
    const payload = dataTransfer.getData('application/x-stimma-assets')
    button.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer }))
    return JSON.parse(payload)
  })
  assert.equal(drag.items[0].media_id, 1)
  await surface.dispatchEvent('contextmenu', { clientX: 100, clientY: 100 })
  assert.equal(await page.evaluate(() => window.chatVideo.menu.state.value.mediaId), 1)

  // The picture is still the primary slideshow affordance, even during playback.
  await surface.click()
  assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [1])
  await expect(hero.locator('video')).toHaveCount(0)

  // Switching away tears down the decoder; ordinary images still open normally.
  await hero.getByRole('checkbox', { name: 'Select this image' }).click()
  await play.focus(); await page.keyboard.press('Escape')
  await expect(hero.getByRole('checkbox')).toHaveAttribute('aria-checked', 'false')
  await play.focus(); await page.keyboard.press('ArrowRight')
  await expect(hero.locator('video')).toHaveCount(0)
  await hero.locator('.group.cursor-pointer').click()
  assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [1, 2])
  if (phone) {
    await page.locator('[data-tile="0"]').click()
    await expect(play).toBeVisible()
    await surface.dispatchEvent('pointerdown', { pointerType: 'touch', clientX: 300, clientY: 200 })
    await surface.dispatchEvent('pointermove', { pointerType: 'touch', clientX: 100, clientY: 200 })
    await surface.dispatchEvent('pointerup', { pointerType: 'touch', clientX: 100, clientY: 200 })
    await expect(hero.getByRole('button', { name: '2 / 2' })).toBeVisible()
    assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [1, 2])
  }

  if (!phone) {
    await page.getByRole('radio', { name: 'Grid' }).click()
    const tile = page.locator('[data-tile="0"]')
    await expect(tile.locator('img').first()).toHaveAttribute('src', /mode=fit/)
    await tile.hover()
    await expect.poll(() => tile.locator('video').evaluate(v => !v.paused && v.muted)).toBe(true)
    await page.mouse.move(1100, 850)
    await expect(tile.locator('video')).toHaveCount(0)
  }
  if (!phone) {
    const shown = page.getByTestId('shown-video')
    await shown.scrollIntoViewIfNeeded()
    await expect.poll(() => shown.locator('img').evaluate(img => img.naturalWidth / img.naturalHeight)).toBe(320 / 180)
    await shown.screenshot({ path: '/tmp/chat-video-uncropped-poster.png' })
    await shown.hover()
    await expect.poll(() => shown.locator('video').evaluate(v => !v.paused)).toBe(true)
    assert.equal(await shown.locator('video').evaluate(v => getComputedStyle(v).objectFit), 'contain')
    await shown.screenshot({ path: '/tmp/chat-video-uncropped-hover.png' })
    await page.mouse.move(0, 0)
    await expect(shown.locator('video')).toHaveCount(0)
  }
  assert.deepEqual(errors, [])
})
