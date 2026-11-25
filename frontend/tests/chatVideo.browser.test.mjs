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
    if (/\/media\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').at(-1)), file_format: path.endsWith('/1') ? 'webm' : 'png', width: 320, height: 180, audio_codec: path.endsWith('/1') ? 'opus' : null } })
    return route.fulfill({ json: {} })
  })
  await page.goto(`http://chat-video.test/${phone ? '?viewport=compact&pointer=coarse' : ''}`)
  // Generate a real playable clip in the browser without a checked-in binary.
  video = Buffer.from(await page.evaluate(async () => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180
    const context = canvas.getContext('2d'); context.fillStyle = 'teal'; context.fillRect(0, 0, 320, 180)
    const stream = canvas.captureStream(10)
    // A tone, so the clip has a sound track for the speaker to find.
    const audio = new AudioContext(); const tone = audio.createOscillator(); const out = audio.createMediaStreamDestination()
    tone.connect(out); tone.start(); stream.addTrack(out.stream.getAudioTracks()[0])
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8,opus' })
    const chunks = []
    const done = new Promise(resolve => { recorder.ondataavailable = e => chunks.push(e.data); recorder.onstop = resolve })
    const draw = setInterval(() => { context.fillStyle = `rgb(0, ${Math.floor(Math.random() * 150)}, 120)`; context.fillRect(0, 0, 320, 180) }, 40)
    recorder.start(); await new Promise(resolve => setTimeout(resolve, 2000)); recorder.stop(); await done; clearInterval(draw)
    stream.getTracks().forEach(track => track.stop()); tone.stop(); await audio.close()
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
  // In a collection a video loops silently on its own: no hover, no play button.
  await expect(hero.getByRole('button', { name: 'Play video' })).toHaveCount(0)
  const poster = hero.locator('img').first()
  await expect(poster).toHaveAttribute('src', /mode=fit/)
  await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && v.muted && v.loop)).toBe(true)
  const surface = hero.locator('[data-video-surface]')
  const toolbar = hero.getByTestId('media-collection-toolbar')
  const add = toolbar.getByRole('button', { name: 'Add to message' })
  const sound = toolbar.getByRole('button', { name: /Play sound once/ })
  await page.screenshot({ path: `/tmp/chat-video-${phone ? 'touch' : 'mouse'}.png` })
  // One row under the picture carries its controls; the slideshow is the picture's click.
  assert.ok((await add.boundingBox()).y >= (await surface.boundingBox()).y + (await surface.boundingBox()).height - 1)
  await expect(hero.getByRole('button', { name: 'Open slideshow' })).toHaveCount(0)
  await expect(hero.getByLabel('Video')).toHaveCount(0)

  // The speaker plays one pass with sound from the top, then the quiet loop returns.
  await sound.click()
  await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && !v.muted && !v.loop)).toBe(true)
  await expect.poll(() => hero.locator('video').evaluate(v => v.muted && v.loop && !v.paused), { timeout: 8000 }).toBe(true)

  await add.click()
  await expect(toolbar.getByRole('button', { name: 'Remove from message' })).toBeVisible()
  assert.deepEqual(await page.evaluate(() => window.chatVideo.attachments.value.map(a => a.media_id)), [1])
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

  // The picture is the slideshow affordance; the loop keeps going behind it.
  await surface.click()
  assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [1])
  await expect(hero.locator('video')).toHaveCount(1)

  const collection = page.getByTestId('media-collection')
  if (!phone) {
    // The pick box floats over the picture's corner on hover.
    await surface.hover()
    await hero.getByRole('checkbox', { name: 'Select this image' }).click()
    await expect(hero.getByRole('checkbox')).toHaveAttribute('aria-checked', 'true')
    await collection.focus(); await page.keyboard.press('Escape')
    await expect(hero.getByRole('checkbox')).toHaveAttribute('aria-checked', 'false')
  } else {
    // Touch picks with a long press, so the box isn't on screen until then.
    await expect(hero.getByRole('checkbox', { name: 'Select this image' })).toBeHidden()
  }
  // Switching away tears down the decoder; ordinary images still open normally.
  await collection.focus(); await page.keyboard.press('ArrowRight')
  await expect(hero.locator('video')).toHaveCount(0)
  await expect(toolbar.getByRole('button', { name: /Play sound once/ })).toHaveCount(0)
  await hero.locator('.group.cursor-pointer').click()
  assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [1, 2])
  if (phone) {
    await page.locator('[data-tile="0"]').click()
    await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && v.muted)).toBe(true)
    await surface.dispatchEvent('pointerdown', { pointerType: 'touch', clientX: 300, clientY: 200 })
    await surface.dispatchEvent('pointermove', { pointerType: 'touch', clientX: 100, clientY: 200 })
    await surface.dispatchEvent('pointerup', { pointerType: 'touch', clientX: 100, clientY: 200 })
    await expect(page.locator('[data-tile="1"]')).toHaveAttribute('aria-current', 'true')
    assert.deepEqual(await page.evaluate(() => window.chatVideo.opened), [1, 2])
  }

  if (!phone) {
    await page.getByRole('radio', { name: 'Grid' }).click()
    const tile = page.locator('[data-tile="0"]')
    await expect(tile.locator('img').first()).toHaveAttribute('src', /mode=fit/)
    // Grid tiles loop too, without waiting for the pointer, at the picture's own shape.
    await expect.poll(() => tile.locator('video').evaluate(v => !v.paused && v.muted && v.loop)).toBe(true)
    const box = await tile.boundingBox()
    assert.ok(Math.abs(box.width / box.height - 320 / 180) < 0.02)
  }
  if (phone) {
    // Touch has no hover: Add stays on the tile; picking is a long press.
    await page.getByRole('button', { name: 'Show grid' }).click()
    const tile = page.locator('[data-tile="1"]')
    await expect(tile.getByRole('button', { name: 'Add to message' })).toBeVisible()
    await expect(tile.getByRole('checkbox')).toBeHidden()
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
