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
    if (!id.endsWith('/src/views/ImageEditorView.vue')) return
    return source.replace('</script>', 'defineExpose({ tools, modelToolParams, repaintToolId, defaultUpscaleToolId, loading, activeReferenceLimits })\n</script>')
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

function fullTool(id, taskType) {
  return {
    full_tool_id: `p:${id}`, tool_id: id, name: id, task_type: taskType, task_types: [taskType],
    provider_id: 'p', provider_name: 'Test Provider', availability: 'available', metadata: {},
    parameter_schema: { properties: {
      prompt: { type: 'string', default: '' },
      input_images: { type: 'array', minItems: 1, maxItems: 3 },
      steps: { type: 'integer', default: 28 },
      scale: { type: 'number', default: 2 },
    } },
    output_schema: {},
  }
}
const CATALOG = [fullTool('repaint', 'inpaint-image'), fullTool('repaint-alt', 'inpaint-image'), fullTool('upscale', 'upscale-image')]
const summary = ({ parameter_schema, output_schema, ...rest }) => ({
  ...rest, parameter_outline: { properties: { input_images: parameter_schema.properties.input_images } },
})

test('the editor lists summaries and reads schemas only for the tools it uses', async t => {
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
    if (path === '/api/tools/providers/tools') return route.fulfill({ json: url.searchParams.get('view') === 'summary' ? CATALOG.map(summary) : CATALOG })
    if (path.startsWith('/api/tools/provider-tool/')) {
      const tool = CATALOG.find(item => item.full_tool_id === path.slice('/api/tools/provider-tool/'.length))
      return tool ? route.fulfill({ json: tool }) : route.fulfill({ status: 404, json: {} })
    }
    if (path.includes('tools') || path.includes('markers') || path.includes('fonts')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://editor.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })

  await expect.poll(() => page.evaluate(() => window.editorTest?.loading)).toBe(false)
  // The picked repaint tool's defaults come from its schema, read on demand.
  await expect.poll(() => page.evaluate(() => window.editorTest.modelToolParams['p:repaint']?.steps ?? null)).toBe(28)
  await page.waitForTimeout(500)
  const catalogReads = reads.filter(read => read.path === '/api/tools/providers/tools')
  assert.deepEqual(catalogReads.map(read => read.view), ['summary'])
  const schemaReads = reads.filter(read => read.path.startsWith('/api/tools/provider-tool/')).map(read => read.path.split('/').pop())
  // The repaint pick (its defaults) and the default upscaler (the output
  // stage) — not the alternative nobody picked — each read once.
  assert.deepEqual(schemaReads.sort(), ['p:repaint', 'p:upscale'])
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
