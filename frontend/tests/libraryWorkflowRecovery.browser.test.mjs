import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { mkdirSync } from 'node:fs'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const root = fileURLToPath(new URL('..', import.meta.url))
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error', root,
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/libraryWorkflowRecovery.ts', import.meta.url)), name: 'WorkflowRecoveryTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const entities = name => ({ chats: name ? [{ id: 1, name, project_id: null }] : [], boards: [], flows: [], projects: [], presets: [] })

async function open(t, { start = '/elsewhere', respond = () => undefined, touch = false, deadline = 1500 } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: touch ? 390 : 1280, height: 844 }, isMobile: touch, hasTouch: touch })
  page.setDefaultTimeout(7000)
  const errors = []
  const requests = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div>' })
    if (path.endsWith('/file')) return route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="512" height="512" fill="${path.includes('left') ? '#c7d2fe' : '#a7f3d0'}"/><circle cx="256" cy="256" r="150" fill="#0f766e"/></svg>` })
    requests.push({ path, method: route.request().method(), body: route.request().postData() })
    let answer = await respond(path, url.searchParams, route.request())
    if (typeof answer === 'number') return route.fulfill({ status: answer, json: { detail: 'Test unavailable' } }).catch(() => {})
    if (answer === undefined) {
      if (path === '/api/settings') answer = { profiles: [{ id: 'test', name: 'Test' }], folders: [], markers: [], wildcards: [], llm_settings: [], tool_providers: [], background_work: { face_detection: { enabled: true, parallelism: 2, min_confidence: 0.5, max_faces: 10 }, clip: { enabled: true } } }
      else if (path === '/api/models/available') answer = { models: [] }
      else if (path === '/api/search') answer = entities('')
      else if (path === '/api/tools/providers' || path === '/api/tools/providers/tools') answer = []
      else if (path === '/api/assets/search-groups' || path === '/api/assets/contextual-media') answer = { groups: [] }
      else if (path === '/api/assets/browse') answer = { items: [], total: 0 }
      else if (path.includes('markers') || path === '/api/projects') answer = []
      else answer = {}
    }
    return route.fulfill({ json: answer }).catch(() => {})
  })
  await page.goto(`http://workflow-recovery.test/?start=${encodeURIComponent(start)}&deadline=${deadline}${touch ? '&viewport=compact&pointer=coarse' : ''}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => !!window.workflowTest)).toBe(true)
  t.after(() => assert.deepEqual(errors, []))
  return { page, requests }
}

test('search shows fast categories, reports HTTP failures and timeouts, and retries only failed reads', async t => {
  let failAssets = true
  const { page, requests } = await open(t, { start: '/search?q=poster',
    respond: (path, query) => {
      if (path === '/api/search') return entities('Poster chat')
      if (path === '/api/assets/search-groups' && failAssets) return 503
      if (path === '/api/assets/browse' && query.has('similar_to_text') && failAssets) return new Promise(() => {})
    },
  })
  await expect(page.getByText('Poster chat', { exact: true })).toBeVisible()
  await expect(page.locator('[data-search-failures]')).toContainText('Assets')
  await expect(page.locator('[data-search-failures]')).toContainText('Visual matches')
  await expect(page.getByText('No matches for “poster”')).toHaveCount(0)
  const entityReads = requests.filter(request => request.path === '/api/search').length
  failAssets = false
  await page.getByRole('button', { name: 'Retry failed searches' }).click()
  await expect(page.getByText('Searching…', { exact: true })).toBeHidden()
  await expect(page.locator('[data-search-failures]')).toHaveCount(0)
  assert.equal(requests.filter(request => request.path === '/api/search').length, entityReads)
})

test('omnibox exposes partial failure and a newer query cannot receive stale results', async t => {
  let releaseOld
  const { page } = await open(t, { respond: (path, query) => {
    if (path === '/api/search') {
      if (query.get('q') === 'old') return new Promise(resolve => { releaseOld = () => resolve(entities('Old chat')) })
      return entities('New chat')
    }
    if (path === '/api/assets/search-groups') return 503
  } })
  const search = page.getByPlaceholder('Search or jump to…')
  await search.fill('old')
  await expect.poll(() => !!releaseOld).toBe(true)
  await search.fill('new')
  await expect(page.getByText('New chat', { exact: true })).toBeVisible()
  releaseOld()
  await expect(page.getByText('Old chat', { exact: true })).toHaveCount(0)
  await expect(page.locator('[data-search-failures]')).toContainText('Assets')
})

for (const touch of [false, true]) test(`Settings search finds synonyms and highlights the destination (${touch ? 'touch' : 'desktop'})`, async t => {
  const { page } = await open(t, { touch })
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const search = page.getByRole('searchbox', { name: 'Search settings' })
  await search.fill('dark')
  await page.getByRole('button', { name: 'Theme Preferences' }).click()
  await expect(page.locator('[data-setting-label="Theme"]')).toBeVisible()
  await expect(page.locator('[data-setting-label="Theme"]')).toHaveClass(/ring-2/)
  await search.fill('clip')
  await page.getByRole('button', { name: 'Visual indexing Background work' }).click()
  await expect(page.locator('[data-setting-label="Visual indexing"]')).toBeVisible()
  await expect(page.locator('[data-setting-label="Visual indexing"]')).toHaveClass(/ring-2/)
  for (const [query, name, target] of [
    ['wildcards', 'Wildcards Prompt variables', 'prompt-wildcards'],
    ['segments', 'Segments Prompt variables', 'prompt-segments'],
    ['version', 'About About', 'about-build'],
    ['login', 'Stimma account Stimma account', 'stimma-account'],
  ]) {
    await search.fill(query)
    await page.getByRole('button', { name, exact: true }).click()
    const destination = page.locator(`[data-settings-target="${target}"]`)
    await expect(destination).toBeVisible()
    await expect(destination).toHaveClass(/ring-2/)
    await expect(destination).toBeFocused()
  }
  await search.fill('no-such-setting')
  await expect(page.getByText('No settings match “no-such-setting”.')).toBeVisible()
  await search.press('Escape')
  await expect(search).toHaveValue('')
  mkdirSync(`${root}/test-results/workflow-recovery`, { recursive: true })
  await page.screenshot({ animations: 'disabled', path: `${root}/test-results/workflow-recovery/settings-${touch ? 'touch' : 'desktop'}.png` })
})

test('Compare supports real touch dragging, pointer capture, pinch zoom, pan, reset and compact info', async t => {
  const { page } = await open(t, { touch: true })
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  const surface = page.locator('[data-compare-canvas]')
  await expect(surface).toHaveCSS('touch-action', 'none')
  const box = await surface.boundingBox()
  assert.ok(box.width > 380, 'comparison keeps the phone width')
  const client = await page.context().newCDPSession(page)
  const point = (id, x, y) => ({ id, x, y, radiusX: 2, radiusY: 2 })
  const y = box.y + box.height / 2
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(1, 100, y)] })
  await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point(1, 450, y)] })
  await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await expect.poll(() => page.evaluate(() => window.workflowTest.slider.value)).toBeGreaterThan(70)
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(1, 150, y), point(2, 250, y)] })
  await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point(1, 100, y), point(2, 300, y)] })
  await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  const zoom = page.getByRole('button', { name: 'Toggle zoom' })
  await expect(zoom).toHaveText('200%')
  const transform = () => surface.locator(':scope > div').first().getAttribute('style')
  const beforePan = await transform()
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(1, 40, y)] })
  await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point(1, 100, y + 40)] })
  await client.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] })
  assert.notEqual(await transform(), beforePan)
  await zoom.tap()
  await expect(zoom).toHaveText('100%')
  await page.getByRole('button', { name: 'Toggle image information' }).tap()
  await expect(page.getByRole('radio', { name: 'Right image' })).toBeInViewport()
  mkdirSync(`${root}/test-results/workflow-recovery`, { recursive: true })
  await page.screenshot({ animations: 'disabled', path: `${root}/test-results/workflow-recovery/compare-touch.png` })
})

test('trash Undo captures server-confirmed asset IDs and works after navigating away', async t => {
  const { page, requests } = await open(t, { respond: (path, _query, request) => {
    if (path === '/api/assets/batch/trash') return { asset_ids: [8, 9] }
    if (path === '/api/assets/batch/restore') return { asset_ids: JSON.parse(request.postData()).asset_ids }
  } })
  await page.evaluate(() => window.workflowTest.trash.trashAssetsWithUndo([8, 9, 9, 10]))
  await page.evaluate(() => window.workflowTest.router.push('/upload'))
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect.poll(() => requests.filter(request => request.path === '/api/assets/batch/restore').length).toBe(1)
  assert.deepEqual(JSON.parse(requests.find(request => request.path === '/api/assets/batch/restore').body), { asset_ids: [8, 9] })
})

test('failed cancellation keeps the batch visible, duplicate clicks share a request, and retry errors are shown', async t => {
  let failCancel = true
  const { page, requests } = await open(t, { respond: path => {
    if (path === '/api/generate/jobs/2' && failCancel) return 503
    if (path === '/api/generate/jobs/3/retry' || path === '/api/generate/jobs/4') return 503
  } })
  await page.evaluate(() => {
    window.workflowTest.jobs.jobs.value = [1, 2].map(id => ({ id, batch_id: 'batch', status: 'processing' }))
    return Promise.all([window.workflowTest.jobs.cancelAndDismissBatch('batch'), window.workflowTest.jobs.cancelAndDismissBatch('batch')])
  })
  assert.equal(requests.filter(request => request.path === '/api/generate/jobs/2').length, 1)
  assert.equal(await page.evaluate(() => !!window.workflowTest.jobs.batchJobs.value.batch), true)
  await expect(page.getByText(/Could not cancel 1 job/)).toBeVisible()
  failCancel = false
  await page.evaluate(() => window.workflowTest.jobs.cancelAndDismissBatch('batch'))
  assert.equal(await page.evaluate(() => !!window.workflowTest.jobs.batchJobs.value.batch), false)
  assert.equal(await page.evaluate(() => window.workflowTest.jobs.retryJob(3)), false)
  await expect(page.getByText('Could not retry this job. Please try again.')).toBeVisible()
  assert.equal(await page.evaluate(() => window.workflowTest.jobs.cancelJob(4)), false)
  await expect(page.getByText(/Could not cancel this job. It may still be running/)).toBeVisible()
  assert.equal(await page.evaluate(() => window.workflowTest.jobs.dismissJob(4)), false)
  assert.equal(await page.evaluate(() => window.workflowTest.jobs.dismissedJobs.value.has(4)), false)
})

test('Undo refuses to send an asset restore to a different profile', async t => {
  const { page, requests } = await open(t, { respond: path => path === '/api/assets/batch/trash' ? { asset_ids: [8] } : undefined })
  await page.evaluate(() => window.workflowTest.trash.trashAssetsWithUndo([8]))
  await page.evaluate(() => window.workflowTest.profile.setCurrentProfileId('another-profile'))
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(page.getByText(/Switch back to the original profile and server/)).toBeVisible()
  assert.equal(requests.filter(request => request.path === '/api/assets/batch/restore').length, 0)
})

test('Compare preserves mouse dragging and keyboard controls', async t => {
  const { page } = await open(t)
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  const surface = page.locator('[data-compare-canvas]')
  const box = await surface.boundingBox()
  await page.mouse.move(box.x + box.width * 0.25, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.75, box.y + box.height / 2)
  await page.mouse.up()
  await expect.poll(() => page.evaluate(() => window.workflowTest.slider.value)).toBeGreaterThan(70)
  const divider = page.getByRole('slider', { name: 'Comparison divider' })
  await divider.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(divider).toHaveAttribute('aria-valuenow', '70')
  await page.keyboard.press('0')
  await expect(page.getByRole('button', { name: 'Toggle zoom' })).toHaveText('100%')
})

test('upload accepts backend-supported audio, SVG and video formats and reports rejected files', async t => {
  const { page, requests } = await open(t, { start: '/upload', respond: path => {
    if (path === '/api/generate/upload-bulk') return { results: [] }
  } })
  const input = page.locator('input[type=file]')
  for (const ext of ['.mp3', '.wav', '.svg', '.avi', '.mkv']) assert.ok((await input.getAttribute('accept')).includes(ext))
  await input.setInputFiles(['sound.MP3', 'vector.svg', 'video.mkv', 'notes.exe'].map(name => ({ name, mimeType: 'application/octet-stream', buffer: Buffer.from('fixture') })))
  await expect.poll(() => requests.filter(request => request.path === '/api/generate/upload-bulk').length).toBe(1)
  const body = requests.find(request => request.path === '/api/generate/upload-bulk').body
  for (const name of ['sound.MP3', 'vector.svg', 'video.mkv']) assert.ok(body.includes(name))
  assert.ok(!body.includes('notes.exe'))
  await expect(page.getByText(/Skipped 1 unsupported file: notes.exe/)).toBeVisible()
})
