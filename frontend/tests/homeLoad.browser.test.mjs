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
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/homeLoad.ts', import.meta.url)), name: 'HomeLoadTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const HOME_READS = ['/api/chats/previews', '/api/assets/browse', '/api/boards', '/api/flows', '/api/models/available']

function chat(id, name) {
  return { id, name, message_count: 1, project_id: null, updated_at: '2026-01-01T00:00:00Z' }
}

/**
 * Serve Home's API. `respond(path, query)` may return a JSON body, a status
 * number, or a promise of either (to delay); undefined falls back to empty.
 */
async function openHome(t, { start = '/', respond = () => undefined } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const counts = new Map()
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    counts.set(path, (counts.get(path) || 0) + 1)
    let answer = await respond(path, url.searchParams)
    if (typeof answer === 'number') return route.fulfill({ status: answer, json: { detail: 'unavailable' } }).catch(() => {})
    if (answer === undefined) {
      if (path === '/api/models/available') answer = { models: [{ slug: 'test', name: 'Test', available: true, selectable: true }], global_default: 'test', llm_configured: true }
      else if (path === '/api/chats/previews' || path === '/api/assets/browse') answer = { items: [], total: 0 }
      else answer = []
    }
    return route.fulfill({ json: answer }).catch(() => {})
  })
  await page.goto(`http://home-load.test/?start=${encodeURIComponent(start)}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return { page, counts, errors, push: path => page.evaluate(path => window.homeLoadTest.router.push(path), path) }
}

const composer = page => page.locator('.chat-input-textarea')
const recents = page => page.locator('[data-recents-state]')

test('the KeepAlive initial mount reads Home once, and a quick return reuses it', async t => {
  const { page, counts, errors, push } = await openHome(t)
  await expect(composer(page)).toBeVisible()
  await page.waitForTimeout(500)
  for (const path of HOME_READS) assert.equal(counts.get(path), 1, `${path} read once on mount`)
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')

  await push('/elsewhere')
  await expect(page.locator('#elsewhere')).toBeVisible()
  await push('/')
  await expect(composer(page)).toBeVisible()
  await page.waitForTimeout(300)
  for (const path of HOME_READS.slice(0, 4)) assert.equal(counts.get(path), 1, `${path} not reread while fresh`)
  assert.deepEqual(errors, [])
})

test('a slow recents read does not hide the composer, and neither does slow artwork', async t => {
  let releaseChats
  const chatsGate = new Promise(resolve => { releaseChats = resolve })
  const { page, errors } = await openHome(t, {
    respond: async path => {
      if (path === '/api/chats/previews') { await chatsGate; return { items: [chat(1, 'Late chat')], total: 1 } }
      if (path === '/api/boards') return [{ id: 5, name: 'Mood board', asset_count: 2, updated_at: '2025-01-01T00:00:00Z' }]
      if (path === '/api/boards/5') return new Promise(() => {})
    },
  })
  await expect(composer(page)).toBeVisible()
  await expect(composer(page)).toBeEditable()
  await expect(page.locator('main > div > div > div').first()).toHaveCSS('opacity', '1')
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'loading')
  // Boards arrived; their artwork never does. The card still shows.
  await expect(page.getByText('Mood board')).toBeVisible()
  releaseChats()
  await expect(page.getByText('Late chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  assert.deepEqual(errors, [])
})

test('a failed recents read keeps the composer usable and offers a retry', async t => {
  let fail = true
  const { page, counts } = await openHome(t, {
    respond: path => {
      if (path === '/api/chats/previews') return fail ? 503 : { items: [chat(2, 'Recovered chat')], total: 1 }
    },
  })
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'error')
  await expect(composer(page)).toBeVisible()
  await composer(page).fill('a usable composer')
  await expect(composer(page)).toHaveValue('a usable composer')
  await expect(page.getByText("Couldn't load your recent work.")).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Recovered chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  assert.equal(counts.get('/api/chats/previews'), 2)
})

test('a late response from the previous project never replaces the new one', async t => {
  let releaseFirst
  const firstGate = new Promise(resolve => { releaseFirst = resolve })
  let firstAssetsDone
  const firstAssets = new Promise(resolve => { firstAssetsDone = resolve })
  const { page, push } = await openHome(t, {
    start: '/projects/1',
    respond: async (path, query) => {
      const project = query.get('project_id')
      if (path === '/api/chats/previews') {
        if (project === '1') { await firstGate; return { items: [{ ...chat(11, 'Project one chat'), project_id: 1 }], total: 1 } }
        return { items: [{ ...chat(22, 'Project two chat'), project_id: 2 }], total: 1 }
      }
      if (path === '/api/boards') {
        if (project === '1') { await firstGate; return [{ id: 7, name: 'Project one board', asset_count: 1, project_id: 1 }] }
        return []
      }
      if (path === '/api/assets/browse' && project === '1') { await firstGate; firstAssetsDone(); return { items: [{ id: 99, media_id: 99, file_hash: 'x' }], total: 1 } }
    },
  })
  await expect(composer(page)).toBeVisible()
  await push('/projects/2')
  await expect(page.getByText('Project two chat')).toBeVisible()
  await expect(recents(page)).toHaveAttribute('data-recents-state', 'ready')
  releaseFirst()
  await firstAssets
  await page.waitForTimeout(400)
  await expect(page.getByText('Project two chat')).toBeVisible()
  await expect(page.getByText('Project one chat')).toHaveCount(0)
  await expect(page.getByText('Project one board')).toHaveCount(0)
  await expect(page.getByText('Fresh from this project')).toHaveCount(0)
})
