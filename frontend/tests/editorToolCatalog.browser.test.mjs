import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The image editor lists catalog summaries and reads a tool's schema only for
// the tools it actually uses. Expose its tool state in the fixture build only.
const observe = {
  name: 'editor-tool-catalog-observer', enforce: 'pre',
  transform(source, id) {
    // The editor fixture never initializes the API config, so the socket
    // would never connect; let the test do it.
    if (id.endsWith('/src/apiConfig.js')) return `${source}\nwindow.__initApiConfig = initApiConfig\n`
    if (!id.endsWith('/src/views/ImageEditorView.vue')) return
    return source.replace('</script>', 'defineExpose({ tools, modelToolParams, repaintToolId, defaultUpscaleToolId, loading, ensureFullTool, selection, selModel, onSelectionChange, selectFamily, selectSub })\n</script>')
  },
}
const base = config({})
const built = await build({
  ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  plugins: [observe, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/editorRendering.ts', import.meta.url)), name: 'EditorToolCatalogTest', formats: ['iife'],
  } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

function fullTool(id, taskType, steps = 28) {
  return {
    full_tool_id: `p:${id}`, tool_id: id, name: id, task_type: taskType, task_types: [taskType],
    provider_id: 'p', provider_name: 'Test Provider', availability: 'available', metadata: {},
    parameter_schema: { properties: {
      prompt: { type: 'string', default: '' },
      input_images: { type: 'array', minItems: 1, maxItems: 3 },
      steps: { type: 'integer', default: steps },
      scale: { type: 'number', default: 2 },
    } },
    output_schema: {},
  }
}
const CATALOG = [fullTool('repaint', 'inpaint-image'), fullTool('repaint-alt', 'inpaint-image'), fullTool('upscale', 'upscale-image')]
const summary = ({ parameter_schema, output_schema, ...rest }) => ({
  ...rest, parameter_outline: { properties: { input_images: parameter_schema.properties.input_images } },
})

/**
 * Open the real editor on a one-layer document. `schema(id)` may answer a
 * schema read with a tool, a status number, or a promise of either.
 */
async function openEditor(t, { catalog = () => CATALOG, schema = id => CATALOG.find(tool => tool.full_tool_id === id) ?? 404 } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const reads = []
  const doc = { format: 'stimma-image-stack', version: 1,
    base: { asset_id: 1, revision_id: 1, media_id: 1, file_hash: 'base', width: 64, height: 64 },
    canvas: { width: 64, height: 64 }, edits: [],
  }
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    const path = decodeURIComponent(url.pathname)
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app" style="height:850px"></div>' })
    reads.push({ path, view: url.searchParams.get('view') })
    if (path === '/api/image-stack/open') return route.fulfill({ json: { document_id: 'fixture', document: doc, base: doc.base, head_revision_id: 1 } })
    if (path.endsWith('/file')) {
      return route.fulfill({ contentType: 'image/png', body: Buffer.from(await page.evaluate(() => {
        const canvas = document.createElement('canvas')
        canvas.width = 64; canvas.height = 64
        canvas.getContext('2d').fillRect(0, 0, 64, 64)
        return canvas.toDataURL('image/png').split(',')[1]
      }), 'base64') })
    }
    if (path.includes('/payloads/')) return route.fulfill({ status: 404 })
    if (path.endsWith('/journal')) return route.fulfill({ json: { entries: [] } })
    if (path === '/api/tools/providers') return route.fulfill({ json: [] })
    if (path === '/api/tools/providers/tools') {
      const tools = catalog()
      return route.fulfill({ json: url.searchParams.get('view') === 'summary' ? tools.map(summary) : tools })
    }
    if (path.startsWith('/api/tools/provider-tool/')) {
      const answer = await schema(path.slice('/api/tools/provider-tool/'.length))
      if (typeof answer === 'number') return route.fulfill({ status: answer, json: { detail: 'unavailable' } }).catch(() => {})
      return route.fulfill({ json: answer }).catch(() => {})
    }
    if (path.includes('tools') || path.includes('markers') || path.includes('fonts')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://editor.test/')
  // A scripted server socket, so the test can broadcast tool changes.
  await page.evaluate(() => {
    window.sockets = []
    window.WebSocket = class {
      static CONNECTING = 0
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3
      readyState = 0
      constructor() { window.sockets.push(this); setTimeout(() => { this.readyState = 1; this.onopen?.() }, 0) }
      send() {}
      close() { this.readyState = 3 }
    }
    window.serverEvent = (event, data = {}) => window.sockets.at(-1)?.onmessage?.({ data: JSON.stringify({ event, data }) })
  })
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.evaluate(() => window.__initApiConfig())
  await expect.poll(() => page.evaluate(() => window.sockets.length)).toBeGreaterThan(0)
  await expect.poll(() => page.evaluate(() => window.editorTest?.loading)).toBe(false)
  return { page, errors, reads }
}

const schemaReadsOf = reads => reads.filter(read => read.path.startsWith('/api/tools/provider-tool/')).map(read => read.path.split('/').pop())

for (const picker of ['model', 'advanced', 'save']) {
  test(`dismissing the inpaint ${picker} picker on the matte preserves selection until the next click`, async t => {
    const { page, errors } = await openEditor(t)
    await page.evaluate(() => {
      const editor = window.editorTest
      editor.selectFamily('generate')
      editor.selectSub('repaint')
      const mask = document.createElement('canvas')
      mask.width = 64; mask.height = 64
      mask.getContext('2d').fillRect(8, 8, 32, 32)
      editor.selModel.applyMaskCanvas(mask, 'new')
      editor.onSelectionChange(mask)
    })
    await expect.poll(() => page.evaluate(() => !!window.editorTest.tools.find(tool => tool.full_tool_id === 'p:repaint')?.parameter_schema)).toBe(true)
    const menu = picker === 'model' ? page.getByRole('button', { name: 'repaint-alt' })
      : picker === 'advanced' ? page.locator('.editor-picker') : page.getByRole('button', { name: /Save as/ })
    const trigger = { model: 'repaint', advanced: 'Advanced settings', save: 'More save options' }[picker]
    await page.getByRole('button', { name: trigger, exact: true }).click()
    await expect(menu).toBeVisible()
    const matte = page.locator('[data-disable-long-press]')
    await matte.click({ position: { x: 10, y: 200 } })
    await expect(menu).toHaveCount(0)
    assert.equal(await page.evaluate(() => !!window.editorTest.selection), true)
    await matte.click({ position: { x: 10, y: 200 } })
    assert.equal(await page.evaluate(() => !!window.editorTest.selection), false)
    assert.deepEqual(errors, [])
  })
}

test('the editor lists summaries and reads schemas only for the tools it uses', async t => {
  const { page, errors, reads } = await openEditor(t)
  // The picked repaint tool's defaults come from its schema, read on demand.
  await expect.poll(() => page.evaluate(() => window.editorTest.modelToolParams['p:repaint']?.steps ?? null)).toBe(28)
  await page.waitForTimeout(500)
  const catalogReads = reads.filter(read => read.path === '/api/tools/providers/tools')
  assert.deepEqual(catalogReads.map(read => read.view), ['summary'])
  // The repaint pick (its defaults) and the default upscaler (the output
  // stage) — not the alternative nobody picked — each read once.
  assert.deepEqual(schemaReadsOf(reads).sort(), ['p:repaint', 'p:upscale'])
  const state = await page.evaluate(() => {
    const { tools, repaintToolId, defaultUpscaleToolId } = window.editorTest
    const byId = Object.fromEntries(tools.map(tool => [tool.full_tool_id, !!tool.parameter_schema]))
    return { byId, repaintToolId, defaultUpscaleToolId }
  })
  assert.equal(state.repaintToolId, 'p:repaint')
  assert.equal(state.defaultUpscaleToolId, 'p:upscale')
  assert.deepEqual(state.byId, { 'p:repaint': true, 'p:repaint-alt': false, 'p:upscale': true })
  assert.deepEqual(errors, [])
})

test('an obsolete schema that lands after a tool change never seeds or replaces the newer one', async t => {
  let version = 1
  let releaseFirst
  const firstGate = new Promise(resolve => { releaseFirst = resolve })
  let repaintReads = 0
  const { page, errors } = await openEditor(t, {
    catalog: () => CATALOG.map(tool => (tool.full_tool_id === 'p:repaint' ? fullTool('repaint', 'inpaint-image', version * 10) : tool)),
    schema: async id => {
      if (id !== 'p:repaint') return CATALOG.find(tool => tool.full_tool_id === id) ?? 404
      const answer = fullTool('repaint', 'inpaint-image', version * 10)
      if (++repaintReads === 1) await firstGate
      return answer
    },
  })
  await expect.poll(() => repaintReads).toBe(1)
  // Wait until the editor follows tool changes (after its catalog is in).
  await expect.poll(() => page.evaluate(() => window.editorTest.tools.length)).toBe(3)
  await page.waitForTimeout(200)
  version = 2
  await page.evaluate(() => window.serverEvent('tools_updated', {}))
  releaseFirst()
  await expect.poll(() => page.evaluate(() => window.editorTest.modelToolParams['p:repaint']?.steps ?? null)).toBe(20)
  await page.waitForTimeout(500)
  const state = await page.evaluate(() => ({
    seeded: window.editorTest.modelToolParams['p:repaint'].steps,
    listed: window.editorTest.tools.find(tool => tool.full_tool_id === 'p:repaint').parameter_schema.properties.steps.default,
  }))
  assert.deepEqual(state, { seeded: 20, listed: 20 })
  assert.deepEqual(errors, [])
})

test('a schema read that fails reports why and can be retried; only a confirmed absence says removed', async t => {
  let failing = true
  const { page } = await openEditor(t, {
    schema: id => {
      if (id === 'p:repaint-alt') return 404
      if (id === 'p:repaint' && failing) return 503
      return CATALOG.find(tool => tool.full_tool_id === id) ?? 404
    },
  })
  await expect.poll(() => page.evaluate(() => window.editorTest.tools.length)).toBe(3)
  const failed = await page.evaluate(() => window.editorTest.ensureFullTool('p:repaint', { current: true }).then(() => 'resolved', error => error.message))
  assert.match(failed, /Couldn't load this tool's settings/)
  assert.match(failed, /Try again/)
  assert.doesNotMatch(failed, /no longer in the catalog/)
  // A retry once the server answers again succeeds.
  failing = false
  const retried = await page.evaluate(async () => (await window.editorTest.ensureFullTool('p:repaint', { current: true }))?.parameter_schema?.properties?.steps?.default)
  assert.equal(retried, 28)
  // The server no longer knows this one: that, and only that, is "removed".
  assert.equal(await page.evaluate(() => window.editorTest.ensureFullTool('p:repaint-alt', { current: true })), null)
})
