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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/mobileMediaActions.ts', import.meta.url)), name: 'MobileMediaActionsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

for (const source of ['slideshow', 'selection']) for (const projectId of [null, 9]) for (const action of ['remix', 'chat', 'new-chat', 'flow', 'lineage']) for (const [width, height] of action === 'remix' ? [[390, 844], [752, 844], [1100, 844], [752, 420]] : [[390, 844]]) test(`phone ${action} from ${source}, project ${projectId}, ${width}×${height}`, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height }, isMobile: true, hasTouch: true })
  page.setDefaultTimeout(5000)
  const errors = []
  const requests = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), path = url.pathname
    requests.push({ path, query: Object.fromEntries(url.searchParams), method: route.request().method(), body: route.request().postDataJSON() })
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div></body></html>' })
    if (path.includes('/remix-tools/')) return route.fulfill({ json: [{ full_tool_id: 'test:generate', name: 'Test generator', task_type: 'text-to-image', provider_id: 'test', provider_name: 'Test provider', metadata: {}, is_original: true }] })
    if (path.includes('/faces')) return route.fulfill({ json: { faces: [] } })
    if (path.includes('/markers')) return route.fulfill({ json: [] })
    if (path.includes('/media/42') || path.includes('/assets/item/7')) return route.fulfill({ json: { id: 7, asset_id: 7, media_id: 42, file_format: 'png' } })
    if (path === '/api/chats') return route.fulfill({ json: route.request().method() === 'POST' ? { id: 13 } : { items: [{ id: 12, name: 'Destination chat' }] } })
    if (path === '/api/flows') return route.fulfill({ json: [{ id: 15, name: 'Destination flow', input_schema: {} }] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://mobile-media-actions.test/?viewport=compact&pointer=coarse')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.evaluate(id => window.mobileMediaActions.setProject(id), projectId)
  await expect(page.locator('.multi-select-action-bar')).toBeVisible()
  // Verify safe-area spacing with a nonzero inset as on a phone shell.
  await page.evaluate(() => document.documentElement.style.setProperty('--safe-bottom', '34px'))
  for (const bar of [page.locator('.multi-select-action-bar'), page.locator('.entity-selection-fixture > div')]) {
    assert.equal(await bar.evaluate(el => parseFloat(getComputedStyle(el).bottom)), 46)
  }
  // Keep the entity selection bar out of the asset bar's hit area.
  await page.locator('.entity-selection-fixture').evaluate(el => { el.style.display = 'none' })
  if (source === 'slideshow') await page.evaluate(() => window.mobileMediaActions.openSlideshowMenu())
  else await page.getByRole('button', { name: 'More actions' }).tap()
  if (source === 'slideshow') await expect(page.locator('[data-test-header]')).toBeHidden()
  if (action === 'remix') {
    await page.getByRole('button', { name: 'Remix', exact: true }).tap()
    const root = page.locator('[data-context-menu]')
    const search = page.getByPlaceholder('Filter tools...')
    const tool = page.getByRole('button', { name: /Test generator/ })
    await expect(root).toBeHidden()
    await expect(search).not.toBeFocused()
    await expect(tool).toBeVisible()
    assert.equal(await tool.evaluate(el => {
      const box = el.getBoundingClientRect()
      return el.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2))
    }), true, 'the tool row must own its hit area')
    await page.getByRole('button', { name: 'Back to actions' }).tap()
    await expect(root).toBeVisible()
    await page.getByRole('button', { name: 'Remix', exact: true }).tap()
    await search.tap()
    await expect(search).toBeFocused()
    if (width === 752 && height === 420 && source === 'selection' && projectId === null) await page.screenshot({ path: '/tmp/stimma-actions-foldable.png' })
    if (source === 'selection' && projectId === null && width === 752 && height === 844) {
      await page.locator('[data-sheet-backdrop]').tap({ position: { x: 10, y: 10 } })
      await expect(search).toBeHidden()
      await expect(root).toBeHidden()
      await page.getByRole('button', { name: 'More actions' }).tap()
      await page.getByRole('button', { name: 'Remix', exact: true }).tap()
    }
    await tool.tap()
  } else if (action === 'chat' || action === 'new-chat') {
    await page.getByRole('button', { name: 'Send to Chat', exact: true }).tap()
    await page.getByRole('button', { name: action === 'chat' ? 'Destination chat' : 'New Chat', exact: true }).tap()
  } else if (action === 'flow') {
    await page.getByRole('button', { name: 'Send to Flow', exact: true }).tap()
    await page.getByRole('button', { name: 'Destination flow', exact: true }).tap()
    await page.getByRole('button', { name: 'Attach to Message', exact: true }).tap()
  } else await page.getByRole('button', { name: /Lineage/ }).tap()
  await expect.poll(() => page.evaluate(() => window.mobileMediaActions.route().name)).toBe(action === 'remix' ? 'tool' : action.includes('chat') ? 'chat' : action)
  const route = await page.evaluate(() => window.mobileMediaActions.route())
  if (action === 'remix') {
    assert.equal(route.params.fullToolId, 'test:generate')
    assert.equal(route.query.remixFrom, '42')
    assert.equal(route.query.project_id, String(projectId ?? 0))
    assert.ok(route.query.instance)
  } else if (action.includes('chat')) {
    assert.equal(route.params.id, action === 'chat' ? '12' : '13')
    assert.equal(requests.find(r => r.path === '/api/chats' && r.method === 'GET').query.project_id, projectId == null ? undefined : String(projectId))
    if (action === 'new-chat') assert.equal(requests.find(r => r.path === '/api/chats' && r.method === 'POST').body.project_id, projectId)
  } else if (action === 'flow') {
    assert.equal(route.params.id, '15')
    assert.equal(requests.find(r => r.path === '/api/flows').query.project_id, projectId == null ? undefined : String(projectId))
  } else assert.equal(route.params.mediaId, '42')
  await expect(page.locator('[data-test-header]')).toBeVisible()
  assert.deepEqual(errors, [])
})
