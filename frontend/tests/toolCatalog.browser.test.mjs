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
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/toolCatalog.ts', import.meta.url)), name: 'ToolCatalogTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const PROVIDER = { provider_id: 'p', provider_name: 'Test Provider', provider_type: 'jsonrpc', status: 'connected', tool_count: 2, max_concurrent: 1 }

// A tool as the server's full catalog lists it: schemas with defaults,
// descriptions and enums — the bulk the summary view leaves out.
function fullTool(id, name, profile = 'default') {
  return {
    full_tool_id: `p:${id}`, tool_id: id, name, task_type: 'image-to-image', task_types: ['image-to-image'],
    provider_id: 'p', provider_name: 'Test Provider', subtitle: `${name} for ${profile}`,
    availability: 'available', model_vendor: null, model: null, preview_frames: false,
    metadata: { description: `${name} description`, layout: [{ title: 'Advanced', fields: ['steps'] }], instructions: 'x'.repeat(400) },
    layout: null,
    parameter_schema: { type: 'object', required: ['prompt'], properties: {
      prompt: { type: 'string', description: 'What to make', default: '' },
      input_images: { type: 'array', items: { type: 'string' }, minItems: 1, maxItems: 4, description: 'Images to edit' },
      steps: { type: 'integer', default: 20, minimum: 1, maximum: 50, description: 'Sampling steps' },
      sampler: { type: 'string', enum: ['euler', 'dpm', 'ddim', 'heun', 'lms'], default: 'euler' },
    } },
    output_schema: { type: 'object', properties: { images: { type: 'array', items: { type: 'string' } } } },
  }
}

// The same tool as the summary view returns it (mirrors the backend projection).
function summaryOf(tool) {
  const { parameter_schema, output_schema, layout, metadata, ...rest } = tool
  const keep = ['type', 'minItems', 'maxItems', 'x-min-items', 'x-max-items', 'x-control', 'x-accept-media']
  const media = new Set(['input_images', 'input_image', 'start_image', 'source_image', 'image', 'input_videos', 'input_video', 'input_audios', 'input_audio', 'mask'])
  const properties = {}
  for (const [name, schema] of Object.entries(parameter_schema.properties)) {
    if (media.has(name) || 'x-accept-media' in schema) {
      properties[name] = Object.fromEntries(Object.entries(schema).filter(([key]) => keep.includes(key)))
    }
  }
  return { ...rest, metadata: { description: metadata.description }, parameter_outline: { properties } }
}

const catalogFor = profile => [fullTool('paint', 'Paint', profile), fullTool('upscale', 'Upscale', profile)]

/**
 * Serve the launch surfaces. `oldServer` ignores `view=summary`, as a server
 * from before the summary view does. Records every catalog and schema read.
 */
async function openApp(t, { start = '/', oldServer = false, deadline = null, respond = () => undefined } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  if (process.env.CATALOG_DEBUG) page.on('console', message => { if (/ToolView|ProvidersApi|rror/.test(message.text())) console.log('PAGE', message.text().slice(0, 300)) })
  const reads = []
  const bytes = new Map()
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = decodeURIComponent(url.pathname)
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    const profile = request.headers()['x-profile-id'] || 'default'
    const view = url.searchParams.get('view')
    reads.push({ path, view, profile })
    let answer = await respond(path, url.searchParams, profile)
    if (answer === undefined) {
      if (path === '/api/tools/providers') answer = [PROVIDER]
      else if (path === '/api/tools/providers/tools') {
        const tools = catalogFor(profile)
        answer = view === 'summary' && !oldServer ? tools.map(summaryOf) : tools
      } else if (path.startsWith('/api/tools/provider-tool/')) {
        const id = decodeURIComponent(path.slice('/api/tools/provider-tool/'.length))
        answer = catalogFor(profile).find(tool => tool.full_tool_id === id) ?? 404
      } else if (path.startsWith('/api/tools/state/')) answer = { full_tool_id: '', state: {}, updated_at: null }
      else if (path === '/api/models/available') answer = { models: [{ slug: 'test', name: 'Test', available: true, selectable: true }], global_default: 'test', llm_configured: true }
      else if (path === '/api/chats/previews' || path === '/api/assets/browse') answer = { items: [], total: 0 }
      else answer = []
    }
    if (typeof answer === 'number') return route.fulfill({ status: answer, json: { detail: 'unavailable' } }).catch(() => {})
    const body = JSON.stringify(answer)
    const key = `${path}${view ? `?view=${view}` : ''}`
    bytes.set(key, (bytes.get(key) || 0) + body.length)
    return route.fulfill({ contentType: 'application/json', body }).catch(() => {})
  })
  await page.goto(`http://tool-catalog.test/?start=${encodeURIComponent(start)}${deadline ? `&deadline=${deadline}` : ''}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  const count = (path, filter = () => true) => reads.filter(read => read.path === path && filter(read)).length
  return {
    page, reads, bytes, errors, count,
    catalogReads: () => count('/api/tools/providers/tools'),
    schemaReads: id => count(`/api/tools/provider-tool/${id}`),
    push: path => page.evaluate(path => window.toolCatalogTest.router.push(path), path),
  }
}

const composer = page => page.locator('.chat-input-textarea')

test('launch reads the tool catalog once, as a summary, and no tool schema', async t => {
  const app = await openApp(t)
  await expect(composer(app.page)).toBeVisible()
  // Let the socket connect (the sidebar reloads on connect) and everything settle.
  await app.page.waitForTimeout(1500)
  assert.equal(app.catalogReads(), 1, 'one catalog read for every launch surface')
  assert.equal(app.count('/api/tools/providers/tools', read => read.view === 'summary'), 1, 'the read asks for summaries')
  assert.equal(app.count('/api/tools/providers'), 1, 'one provider read, shared with the provider manager')
  assert.equal(app.reads.filter(read => read.path.startsWith('/api/tools/provider-tool/')).length, 0, 'no schema read at launch')
  // What launch surfaces render is all there.
  const tools = await app.page.evaluate(() => window.toolCatalogTest.catalog.cachedTools.value)
  assert.deepEqual(tools.map(tool => tool.name), ['Paint', 'Upscale'])
  assert.equal(tools[0].metadata.description, 'Paint description')
  assert.equal(tools[0].parameter_schema, undefined)
  const full = JSON.stringify(catalogFor('default')).length
  console.log(`launch catalog bytes: ${app.bytes.get('/api/tools/providers/tools?view=summary')} (summary) vs ${full} per full read`)
  assert.deepEqual(app.errors, [])
})

test('a tool change makes every launch surface reread the catalog together, once', async t => {
  const app = await openApp(t)
  await expect(composer(app.page)).toBeVisible()
  await app.page.waitForTimeout(1500)
  assert.equal(app.catalogReads(), 1)
  await app.page.evaluate(() => window.toolCatalogTest.serverEvent('tools_updated', {}))
  await expect.poll(app.catalogReads).toBe(2)
  await app.page.waitForTimeout(800)
  assert.equal(app.catalogReads(), 2, 'Home, the sidebar and the provider manager share one reread')
  await app.page.evaluate(() => window.toolCatalogTest.serverEvent('provider_status_changed', { provider_id: 'p', status: 'connected', tool_count: 2 }))
  await expect.poll(app.catalogReads).toBe(3)
  await app.page.waitForTimeout(800)
  assert.equal(app.catalogReads(), 3)
})

test('opening a tool reads its schema once, and again only after the catalog changes', async t => {
  const app = await openApp(t, { start: '/elsewhere' })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  // ToolView subscribes to tool changes once its load has finished.
  const loaded = app.page.waitForEvent('console', { predicate: message => message.text().includes('[ToolView onMounted] loadTool completed'), timeout: 20_000 })
  await app.push('/tools/p:paint')
  await expect.poll(() => app.schemaReads('p:paint')).toBe(1)
  await expect(app.page.getByText('Paint').first()).toBeVisible()
  await loaded
  await app.page.waitForTimeout(300)
  assert.equal(app.schemaReads('p:paint'), 1, 'one schema read while the tool opens')
  assert.equal(app.schemaReads('p:upscale'), 0, 'only the opened tool')
  // Other readers of the same tool (send-to, chain steps) share it.
  const schemas = await app.page.evaluate(async () => {
    const { catalog } = window.toolCatalogTest
    const tools = await Promise.all([catalog.getProviderTool('p:paint'), catalog.getProviderTool('p:paint'), catalog.getTool('p:paint')])
    // Each caller gets its own copy to build state on.
    tools[0].parameter_schema.properties.steps.default = 99
    return tools.map(tool => tool.parameter_schema.properties.steps.default)
  })
  assert.deepEqual(schemas, [99, 20, 20])
  assert.equal(app.schemaReads('p:paint'), 1)
  // A tool change: the open ToolView rereads its tool, once.
  await app.page.evaluate(() => window.toolCatalogTest.serverEvent('tools_updated', {}))
  await expect.poll(() => app.schemaReads('p:paint')).toBe(2)
  await app.page.evaluate(() => window.toolCatalogTest.catalog.getProviderTool('p:paint'))
  await app.page.waitForTimeout(400)
  assert.equal(app.schemaReads('p:paint'), 2)
})

test('against an older server the full catalog is used as is, with no schema reads', async t => {
  const app = await openApp(t, { oldServer: true })
  await expect(composer(app.page)).toBeVisible()
  await app.page.waitForTimeout(1500)
  assert.equal(app.catalogReads(), 1)
  await app.push('/tools/p:paint')
  await expect(app.page.getByText('Paint').first()).toBeVisible()
  await app.page.waitForTimeout(800)
  const tool = await app.page.evaluate(() => window.toolCatalogTest.catalog.getProviderTool('p:paint'))
  assert.equal(tool.parameter_schema.properties.steps.default, 20)
  assert.equal(app.reads.filter(read => read.path.startsWith('/api/tools/provider-tool/')).length, 0)
  // Send-to eligibility reads the full schema the same way.
  const plan = await app.page.evaluate(() => {
    const { catalog, planToolHandoff } = window.toolCatalogTest
    const tool = catalog.cachedTools.value.find(t => t.full_tool_id === 'p:paint')
    return planToolHandoff({ tool, mediaTypes: ['image'], count: 3 })
  })
  assert.equal(plan.eligible, true)
})

test('send-to eligibility from a summary matches the full tool', async t => {
  const app = await openApp(t)
  await expect(composer(app.page)).toBeVisible()
  const plans = await app.page.evaluate(async () => {
    const { catalog, planToolHandoff } = window.toolCatalogTest
    const summary = (await catalog.fetchProvidersAndTools()).tools.find(t => t.full_tool_id === 'p:paint')
    const full = await catalog.getProviderTool('p:paint')
    const cases = [
      { mediaTypes: ['image'], count: 1 }, { mediaTypes: ['image'], count: 3 },
      { mediaTypes: ['video'], count: 1 }, { mediaTypes: ['audio'], count: 1 },
    ]
    return cases.map(c => [planToolHandoff({ tool: summary, ...c }), planToolHandoff({ tool: full, ...c })])
  })
  for (const [fromSummary, fromFull] of plans) assert.deepEqual(fromSummary, fromFull)
})

test('catalog and schema caches belong to one server profile', async t => {
  const app = await openApp(t, { start: '/elsewhere' })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  await app.page.waitForTimeout(800)
  const result = await app.page.evaluate(async () => {
    const { catalog, setProfile } = window.toolCatalogTest
    setProfile('a')
    window.dispatchEvent(new Event('profile-changed'))
    const a = await catalog.getProviderTool('p:paint')
    const aCatalog = (await catalog.fetchProvidersAndTools()).tools[0].subtitle
    setProfile('b')
    window.dispatchEvent(new Event('profile-changed'))
    const b = await catalog.getProviderTool('p:paint')
    const bCatalog = (await catalog.fetchProvidersAndTools()).tools[0].subtitle
    // Back to a: its schema is read again rather than served from b's.
    setProfile('a')
    window.dispatchEvent(new Event('profile-changed'))
    const again = await catalog.getProviderTool('p:paint')
    return [a.subtitle, aCatalog, b.subtitle, bCatalog, again.subtitle]
  })
  assert.deepEqual(result, ['Paint for a', 'Paint for a', 'Paint for b', 'Paint for b', 'Paint for a'])
  const schemaProfiles = app.reads.filter(read => read.path === '/api/tools/provider-tool/p:paint').map(read => read.profile)
  assert.deepEqual(schemaProfiles, ['a', 'b', 'a'])
})

test('a profile switch while a catalog read is in flight never shares it with the new profile', async t => {
  let releaseA
  const gateA = new Promise(resolve => { releaseA = resolve })
  const app = await openApp(t, {
    start: '/elsewhere',
    respond: async (path, query, profile) => {
      if (path === '/api/tools/providers/tools' && profile === 'a') { await gateA; return catalogFor('a').map(summaryOf) }
    },
  })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  await app.page.waitForTimeout(800)
  const forB = await app.page.evaluate(async () => {
    const { catalog, setProfile } = window.toolCatalogTest
    setProfile('a')
    window.dispatchEvent(new Event('profile-changed'))
    void catalog.fetchProvidersAndTools().catch(() => {})
    await new Promise(resolve => setTimeout(resolve, 100))
    setProfile('b')
    window.dispatchEvent(new Event('profile-changed'))
    // Joining A's read would wait on the held read; B gets its own.
    return (await catalog.fetchProvidersAndTools()).tools.map(tool => tool.subtitle)
  })
  assert.deepEqual(forB, ['Paint for b', 'Upscale for b'])
  releaseA()
  await app.page.waitForTimeout(400)
  const cached = await app.page.evaluate(() => window.toolCatalogTest.catalog.cachedTools.value.map(tool => tool.subtitle))
  assert.deepEqual(cached, ['Paint for b', 'Upscale for b'])
})

test('callers that give up on a shared catalog read cancel it only when nobody else waits', async t => {
  const held = { gate: null }
  const app = await openApp(t, {
    start: '/elsewhere',
    respond: async path => {
      if (path === '/api/tools/providers/tools' && held.gate) await held.gate
    },
  })
  let cancelled = 0
  app.page.on('requestfailed', request => { if (new URL(request.url()).pathname === '/api/tools/providers/tools') cancelled++ })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  await app.page.waitForTimeout(800)
  const hold = () => {
    let release
    held.gate = new Promise(resolve => { release = resolve })
    return () => { held.gate = null; release() }
  }

  // Two callers share one read; the first gives up, the second still gets it.
  let release = hold()
  const before = app.catalogReads()
  await app.page.evaluate(() => {
    const { catalog } = window.toolCatalogTest
    catalog.clearCache()
    const first = new AbortController()
    window.firstOutcome = catalog.fetchProvidersAndTools(false, { signal: first.signal }).then(() => 'resolved', error => error.name)
    window.secondOutcome = catalog.fetchProvidersAndTools().then(result => result.tools.length, error => error.name)
    window.abortFirst = () => first.abort()
  })
  await expect.poll(app.catalogReads).toBe(before + 1)
  await app.page.evaluate(() => window.abortFirst())
  assert.equal(await app.page.evaluate(() => window.firstOutcome), 'AbortError')
  await app.page.waitForTimeout(300)
  assert.equal(cancelled, 0, 'the read is still wanted by the second caller')
  release()
  assert.equal(await app.page.evaluate(() => window.secondOutcome), 2)
  assert.equal(app.catalogReads(), before + 1, 'both callers joined one read')

  // A caller alone on a read cancels it when it gives up.
  release = hold()
  await app.page.evaluate(() => {
    const { catalog } = window.toolCatalogTest
    catalog.clearCache()
    const only = new AbortController()
    window.loneOutcome = catalog.fetchProvidersAndTools(false, { signal: only.signal }).then(() => 'resolved', error => error.name)
    window.abortLone = () => only.abort()
  })
  await expect.poll(app.catalogReads).toBe(before + 2)
  await app.page.evaluate(() => window.abortLone())
  assert.equal(await app.page.evaluate(() => window.loneOutcome), 'AbortError')
  await expect.poll(() => cancelled).toBe(1)
  release()
})

// A tool whose schema default and availability say which version answered.
function versioned(version, availability = 'available') {
  const tool = fullTool('paint', 'Paint')
  tool.parameter_schema.properties.steps.default = version * 10
  tool.availability = availability
  return tool
}

test('a schema read that a tool change overtakes never wins: callers end on the newer schema', async t => {
  let version = 1
  let releaseFirst
  const firstGate = new Promise(resolve => { releaseFirst = resolve })
  let schemaReads = 0
  const app = await openApp(t, {
    start: '/elsewhere',
    respond: async path => {
      if (path !== '/api/tools/provider-tool/p:paint') return
      const answer = versioned(version)
      if (++schemaReads === 1) await firstGate
      return answer
    },
  })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  await app.page.evaluate(() => { window.pending = window.toolCatalogTest.catalog.getProviderTool('p:paint') })
  await expect.poll(() => schemaReads).toBe(1)
  // The tool changes while v1 is in flight; then the v1 answer lands.
  version = 2
  await app.page.evaluate(() => window.toolCatalogTest.serverEvent('tools_updated', {}))
  releaseFirst()
  const steps = await app.page.evaluate(async () => (await window.pending).parameter_schema.properties.steps.default)
  assert.equal(steps, 20, 'the caller gets the schema read after the change')
  const cached = await app.page.evaluate(async () => (await window.toolCatalogTest.catalog.getProviderTool('p:paint')).parameter_schema.properties.steps.default)
  assert.equal(cached, 20, 'and only the newer schema is kept')
  assert.equal(schemaReads, 2)
})

test('a stalled schema read is bounded by the read deadline, and a later open recovers', async t => {
  let schemaReads = 0
  const app = await openApp(t, {
    start: '/elsewhere',
    deadline: 1500,
    respond: path => {
      if (path !== '/api/tools/provider-tool/p:paint') return
      return ++schemaReads === 1 ? new Promise(() => {}) : undefined
    },
  })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  const first = await app.page.evaluate(() =>
    window.toolCatalogTest.catalog.getProviderTool('p:paint').then(() => 'resolved', error => error.name || error.code || 'failed'))
  assert.notEqual(first, 'resolved')
  const second = await app.page.evaluate(async () => (await window.toolCatalogTest.catalog.getProviderTool('p:paint')).name)
  assert.equal(second, 'Paint')
  assert.equal(schemaReads, 2)
})

test('a schema read is cancelled once every caller waiting on it gives up, and only then', async t => {
  const held = { gate: null }
  const app = await openApp(t, {
    start: '/elsewhere',
    respond: async path => {
      if (path === '/api/tools/provider-tool/p:paint' && held.gate) await held.gate
    },
  })
  let cancelled = 0
  app.page.on('requestfailed', request => { if (decodeURIComponent(new URL(request.url()).pathname) === '/api/tools/provider-tool/p:paint') cancelled++ })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  let release
  held.gate = new Promise(resolve => { release = resolve })
  await app.page.evaluate(() => {
    const { catalog } = window.toolCatalogTest
    const a = new AbortController()
    const b = new AbortController()
    window.outcomes = [a, b].map(controller => catalog.getProviderTool('p:paint', { signal: controller.signal }).then(() => 'resolved', error => error.name))
    window.abortA = () => a.abort()
    window.abortB = () => b.abort()
  })
  await expect.poll(() => app.schemaReads('p:paint')).toBe(1)
  await app.page.evaluate(() => window.abortA())
  await app.page.waitForTimeout(300)
  assert.equal(cancelled, 0, 'still wanted by the other caller')
  await app.page.evaluate(() => window.abortB())
  await expect.poll(() => cancelled).toBe(1)
  assert.deepEqual(await app.page.evaluate(() => Promise.all(window.outcomes)), ['AbortError', 'AbortError'])
  held.gate = null
  release()
  assert.equal(app.schemaReads('p:paint'), 1, 'both callers shared one read')
})

test('a newer catalog retires a full tool it disagrees with, and explicit reads are fresh', async t => {
  let current = versioned(1, 'disconnected')
  const app = await openApp(t, {
    start: '/elsewhere',
    respond: path => {
      if (path === '/api/tools/provider-tool/p:paint') return current
      if (path === '/api/tools/providers/tools') return [summaryOf(current)]
    },
  })
  await expect(app.page.locator('#elsewhere')).toBeVisible()
  await app.page.waitForTimeout(500)
  const first = await app.page.evaluate(async () => (await window.toolCatalogTest.catalog.getProviderTool('p:paint')).availability)
  assert.equal(first, 'disconnected')
  // The provider comes back but its event is missed; a later catalog read
  // (here forced, as after the cache expires) says available.
  current = versioned(2, 'available')
  const result = await app.page.evaluate(async () => {
    const { catalog } = window.toolCatalogTest
    const listed = (await catalog.fetchProvidersAndTools(true)).tools[0].availability
    const opened = await catalog.getProviderTool('p:paint')
    return { listed, opened: opened.availability, steps: opened.parameter_schema.properties.steps.default }
  })
  assert.deepEqual(result, { listed: 'available', opened: 'available', steps: 20 })
  // A full tool the catalog agrees with is kept, unless the caller asks fresh.
  const reads = app.schemaReads('p:paint')
  await app.page.evaluate(() => window.toolCatalogTest.catalog.getProviderTool('p:paint'))
  assert.equal(app.schemaReads('p:paint'), reads)
  await app.page.evaluate(() => window.toolCatalogTest.catalog.getProviderTool('p:paint', { fresh: true }))
  assert.equal(app.schemaReads('p:paint'), reads + 1)
})

test('a socket reconnect after an outage rereads the catalog and the tools it may have missed', async t => {
  let current = versioned(1)
  const app = await openApp(t, {
    respond: path => {
      if (path === '/api/tools/provider-tool/p:paint') return current
    },
  })
  await expect(composer(app.page)).toBeVisible()
  await app.page.waitForTimeout(1500)
  assert.equal(app.catalogReads(), 1)
  await app.page.evaluate(() => window.toolCatalogTest.catalog.getProviderTool('p:paint'))
  current = versioned(2)
  // Down, then back: tools_updated may have been sent while nobody listened.
  const sockets = await app.page.evaluate(() => window.toolCatalogTest.socketCount())
  await app.page.evaluate(() => window.toolCatalogTest.dropSocket())
  await expect.poll(() => app.page.evaluate(() => window.toolCatalogTest.socketCount())).toBeGreaterThan(sockets)
  await expect.poll(app.catalogReads).toBe(2)
  await app.page.waitForTimeout(800)
  assert.equal(app.catalogReads(), 2, 'one shared reread')
  const steps = await app.page.evaluate(async () => (await window.toolCatalogTest.catalog.getProviderTool('p:paint')).parameter_schema.properties.steps.default)
  assert.equal(steps, 20)
})
