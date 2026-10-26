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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/toolFeed.ts', import.meta.url)), name: 'ToolFeedTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const job = id => ({ id, status: 'queued', task_type: 'text-to-image', generator_instance_id: 'tool-test:feed@@guid', created_at: '2026-01-01T00:00:00' })

async function openFeed(t, { holdFirstRead = false, jobs = [job(1)] } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  // A current server that sits on every scope acknowledgement until released.
  const server = { scopes: [], heldAcks: [], jobReads: 0, jobs, holdFirstRead, releaseRead: null }
  await page.routeWebSocket(/\/ws(\?.*)?$/, ws => {
    const url = new URL(ws.url())
    ws.send(JSON.stringify({ event: 'connected', data: { realtime_protocol: 1, realtime: {
      protocol: 1, profile_id: url.searchParams.get('profile'), topics: url.searchParams.getAll('topic'),
    } } }))
    ws.onMessage(message => {
      const { event, data } = JSON.parse(String(message))
      if (event !== 'realtime_scope') return
      server.scopes.push(data)
      server.heldAcks.push(() => ws.send(JSON.stringify({ event: 'realtime_scope_applied', data })))
    })
  })
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app"></div></body></html>' })
    if (url.pathname.endsWith('/generate/jobs')) {
      server.jobReads++
      const json = { jobs: [...server.jobs] }
      if (server.holdFirstRead) {
        server.holdFirstRead = false
        await new Promise(resolve => { server.releaseRead = resolve })
      }
      return route.fulfill({ json })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('http://tool-feed.test/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return { page, server, errors }
}

test('a tool feed renders its jobs before the server confirms it, and reconciles on confirmation', async t => {
  const { page, server, errors } = await openFeed(t)

  // The feed subscribes, but its jobs are read and painted without waiting
  // for the acknowledgement.
  await expect.poll(() => server.scopes.some(s => s.topics.includes('generator:tool-test:feed@@guid'))).toBe(true)
  // Well inside the readiness bound (2 s): nothing waits on the socket.
  await expect.poll(() => page.evaluate(() => window.feedInitialized === true), { timeout: 1000 }).toBe(true)
  await expect.poll(() => page.locator('li.job').count(), { timeout: 1000 }).toBe(1)
  assert.equal(server.jobReads, 1)
  assert.equal(server.heldAcks.length > 0, true, 'no acknowledgement has been sent yet')

  // A job queued before the subscription applied is not broadcast to this
  // client; the late confirmation reloads the feed and picks it up.
  server.jobs = [job(2), job(1)]
  for (const ack of server.heldAcks.splice(0)) ack()
  await expect.poll(() => server.jobReads).toBe(2)
  await expect.poll(() => page.locator('li.job').count()).toBe(2)
  assert.deepEqual(errors, [])
})

test('a confirmation reload that overtakes the first read still hides old failures', async t => {
  const failed = { ...job(1), status: 'failed', error: 'from a previous session' }
  const { page, server, errors } = await openFeed(t, { holdFirstRead: true, jobs: [job(2), failed] })
  // The first read is still in flight when the server confirms the feed;
  // the confirmation's quiet reload supersedes it.
  await expect.poll(() => typeof server.releaseRead).toBe('function')
  await expect.poll(() => server.heldAcks.length).toBeGreaterThan(0)
  for (const ack of server.heldAcks.splice(0)) ack()
  await expect.poll(() => server.jobReads).toBe(2)
  server.releaseRead()
  await expect.poll(() => page.evaluate(() => window.feedInitialized === true)).toBe(true)
  // Only the live job shows; the old failure is dismissed as on a plain load.
  await expect.poll(() => page.locator('li.job').evaluateAll(els => els.map(el => el.dataset.id))).toEqual(['2'])
  assert.deepEqual(errors, [])
})
