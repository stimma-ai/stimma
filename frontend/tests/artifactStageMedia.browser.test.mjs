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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/artifactStageMedia.ts', import.meta.url)), name: 'ArtifactStageMediaTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const icon = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>'
const catalog = ['Favorite', 'Star', 'Keep', 'Reject', 'Hero', 'Later'].map((name, i) => ({ id: i + 1, name, color: '#f43f5e', icon_svg: icon }))

async function boot(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  page.setDefaultTimeout(5000)
  const marked = []
  let video
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/*', route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (path.endsWith('/markers')) return route.fulfill({ json: catalog })
    if (path.endsWith('/markers/batch-get')) return route.fulfill({ json: {} })
    if (/\/media\/\d+\/markers\/\d+$/.test(path)) { marked.push(`${request.method()} ${path}`); return route.fulfill({ json: {} }) }
    if (path.includes('mse-loop')) return route.fulfill({ status: 404, json: {} })
    if (path.endsWith('/file')) return route.fulfill({ contentType: 'video/webm', body: video })
    if (path.includes('thumbnail')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="teal"/></svg>' })
    if (path.endsWith('/media/3/content')) return route.fulfill({ json: { title: 'Set', items: [11, 12, 13].map(id => ({ resolved: { id, file_hash: 'h' + id, file_format: 'png' } })) } })
    if (/\/media\/\d+$/.test(path)) return route.fulfill({ json: { id: Number(path.split('/').at(-1)), file_hash: 'hash-1', file_format: 'webm', duration: 1.5 } })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://artifact-stage.test/')
  // A real clip with a sound track, made in the browser.
  video = Buffer.from(await page.evaluate(async () => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180
    const context = canvas.getContext('2d')
    const stream = canvas.captureStream(10)
    const audio = new AudioContext(); const tone = audio.createOscillator(); const out = audio.createMediaStreamDestination()
    tone.connect(out); tone.start(); stream.addTrack(out.stream.getAudioTracks()[0])
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8,opus' })
    const chunks = []
    const done = new Promise(resolve => { recorder.ondataavailable = e => chunks.push(e.data); recorder.onstop = resolve })
    const draw = setInterval(() => { context.fillStyle = `rgb(0, ${Math.floor(Math.random() * 150)}, 120)`; context.fillRect(0, 0, 320, 180) }, 40)
    recorder.start(); await new Promise(resolve => setTimeout(resolve, 1500)); recorder.stop(); await done; clearInterval(draw)
    stream.getTracks().forEach(track => track.stop()); tone.stop(); await audio.close()
    return [...new Uint8Array(await new Blob(chunks).arrayBuffer())]
  }))
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return { page, marked }
}

test('a video in the panel opens the slideshow on click and plays sound once', { timeout: 30000 }, async t => {
  const { page, marked } = await boot(t)
  const stage = page.getByTestId('artifact-stage')
  const video = stage.locator('video')
  await expect.poll(() => video.evaluate(v => !v.paused && v.muted)).toBe(true)
  // The picture is the way into the slideshow; there is no separate button.
  await expect(stage.getByRole('button', { name: 'Open slideshow' })).toHaveCount(0)
  await video.click()
  assert.deepEqual(await page.evaluate(() => window.stage.opened), [1])
  assert.equal(await video.evaluate(v => v.paused), false)
  // Play and pause live on the transport bar and Space.
  await stage.getByTitle('Pause video').click()
  await expect.poll(() => video.evaluate(v => v.paused)).toBe(true)
  assert.deepEqual(await page.evaluate(() => window.stage.opened), [1])
  await stage.focus(); await page.keyboard.press('Space')
  await expect.poll(() => video.evaluate(v => !v.paused)).toBe(true)
  // Sound is one pass with sound, then back to the quiet loop.
  const sound = stage.getByTitle(/Play sound once/)
  await sound.click()
  await expect.poll(() => video.evaluate(v => !v.muted && !v.paused)).toBe(true)
  await expect.poll(() => video.evaluate(v => v.muted && !v.paused), { timeout: 8000 }).toBe(true)
  // Markers sit in the header.
  const markers = page.getByTestId('stage-markers')
  await markers.getByTitle('Add Star').click()
  await expect(markers.getByTitle('Remove Star')).toBeVisible()
  assert.deepEqual(marked, ['POST /api/media/1/markers/2'])
})

test('a narrow panel folds the header markers behind +N', { timeout: 20000 }, async t => {
  const { page, marked } = await boot(t)
  await page.evaluate(() => { window.stage.kind.value = 'png'; window.stage.width.value = 420 })
  const markers = page.getByTestId('stage-markers')
  await expect(markers.getByRole('button', { name: '3 more markers' })).toBeVisible()
  await expect(markers.locator('button[aria-pressed]')).toHaveCount(3)
  await markers.getByRole('button', { name: '3 more markers' }).click()
  await markers.getByTitle('Add Later').click()
  assert.deepEqual(marked, ['POST /api/media/2/markers/6'])
  await page.evaluate(() => { window.stage.width.value = 900 })
  await expect(markers.locator('button[aria-pressed]')).toHaveCount(6)
  // An image opens the slideshow from its picture too.
  await page.getByTestId('artifact-stage').locator('.cursor-zoom-in').click()
  assert.deepEqual(await page.evaluate(() => window.stage.opened), [2])
})

test('a set in the panel is worked in place', { timeout: 20000 }, async t => {
  const { page, marked } = await boot(t)
  await page.evaluate(() => { window.stage.kind.value = 'stimmaset.json' })
  const tiles = page.getByTestId('tile-marker-toggles')
  await expect(tiles).toHaveCount(3)
  await page.locator('.group').nth(1).hover()
  await tiles.nth(1).getByTitle('Add Keep').click()
  assert.deepEqual(marked, ['POST /api/media/12/markers/3'])
  assert.deepEqual(await page.evaluate(() => window.stage.members), [])
  await page.locator('.group').nth(2).click()
  assert.deepEqual(await page.evaluate(() => window.stage.members), [[[11, 12, 13], 2]])
  await expect(page.getByTestId('artifact-stage').locator('pre')).toHaveCount(0)
})
