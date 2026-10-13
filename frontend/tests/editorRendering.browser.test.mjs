import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Expose state only in the in-memory fixture build. Replay, stage publication,
// sidebar events and lifecycle hooks all remain the production implementation.
const observe = {
  name: 'editor-rendering-observer', enforce: 'pre',
  transform(source, id) {
    if (!id.endsWith('/src/views/ImageEditorView.vue')) return
    return source.replace('</script>', 'defineExpose({ stack, composite, cropInput, rendering, loading, error, render, editorRenderer })\n</script>')
  },
}
const base = config({})
const built = await build({
  ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  plugins: [observe, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/editorRendering.ts', import.meta.url)), name: 'EditorRenderingTest', formats: ['iife'],
  } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t, { blockBase = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let releaseBase, baseStarted
  const held = new Promise(resolve => { releaseBase = resolve })
  const started = new Promise(resolve => { baseStarted = resolve })
  // This document starts committed, so teardown doesn't exercise save behavior.
  const doc = { format: 'stimma-image-stack', version: 1,
    base: { asset_id: 1, revision_id: 1, media_id: 1, file_hash: 'base', width: 240, height: 120 },
    canvas: { width: 240, height: 120 }, edits: [{ id: 'crop', class: 'parametric', enabled: true,
      label: 'Crop', exec: { kind: 'crop' }, params: { rect: { x: 0.25, y: 0.5, width: 0.5, height: 1 } } }],
  }
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app" style="height:850px"></div>' })
    if (path === '/api/image-stack/open') return route.fulfill({ json: { document_id: 'fixture', document: doc, base: doc.base, head_revision_id: 1 } })
    if (path.endsWith('/file')) {
      baseStarted()
      if (blockBase) await held
      return route.fulfill({ contentType: 'image/png', body: Buffer.from(await page.evaluate(() => {
        const canvas = document.createElement('canvas')
        canvas.width = 240; canvas.height = 120
        const ctx = canvas.getContext('2d')
        ctx.fillStyle = 'red'; ctx.fillRect(0, 0, 120, 120)
        ctx.fillStyle = 'blue'; ctx.fillRect(120, 0, 120, 120)
        return canvas.toDataURL('image/png').split(',')[1]
      }), 'base64') })
    }
    // A fresh fixture has no persisted materialized head: exercise real replay.
    if (path.includes('/payloads/')) return route.fulfill({ status: 404 })
    if (path.endsWith('/journal')) return route.fulfill({ json: { entries: [] } })
    if (path.includes('tools') || path.includes('markers') || path.includes('fonts')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://editor.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await started
  return { page, errors, releaseBase }
}

async function pixels(page) {
  return page.evaluate(() => {
    const { composite, cropInput } = window.editorTest
    const describe = canvas => canvas ? { size: [canvas.width, canvas.height],
      pixel: [...canvas.getContext('2d').getImageData(10, 10, 1, 1).data] } : null
    return { composite: describe(composite), cropInput: describe(cropInput) }
  })
}

test('the real editor replays sidebar visibility changes and keeps Crop input uncropped', async t => {
  const { page, errors } = await fixture(t)
  await expect.poll(() => page.evaluate(() => window.editorTest.loading)).toBe(false)
  assert.deepEqual((await pixels(page)).composite, { size: [120, 120], pixel: [255, 0, 0, 255] })
  await page.locator('[data-op-id="crop"]').dblclick()
  await expect.poll(() => page.evaluate(() => window.editorTest.cropInput?.width)).toBe(240)
  assert.deepEqual(await pixels(page), {
    composite: { size: [120, 120], pixel: [255, 0, 0, 255] },
    cropInput: { size: [240, 120], pixel: [255, 0, 0, 255] },
  })
  await page.getByRole('button', { name: 'Hide this edit', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.editorTest.composite?.width)).toBe(240)
  assert.equal(await page.evaluate(() => window.editorLiveFrame('1').canvas.width), 240)
  await page.getByRole('button', { name: 'Show this edit', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.editorTest.composite?.width)).toBe(120)
  assert.equal(await page.evaluate(() => window.editorTest.error), null)
  assert.deepEqual(errors, [])
})

test('closing the real editor while its base is decoding cannot resurrect its live preview', async t => {
  const { page, errors, releaseBase } = await fixture(t, { blockBase: true })
  await expect.poll(() => page.evaluate(() => window.editorTest.rendering)).toBe(true)
  await page.evaluate(() => window.unmountEditor())
  releaseBase()
  await expect.poll(() => page.evaluate(() => window.editorTest.rendering)).toBe(false)
  assert.equal(await page.evaluate(() => !!window.editorLiveFrame('1')), false)
  assert.equal(await page.evaluate(() => window.editorTest.composite), null)
  assert.deepEqual(errors, [])
})
