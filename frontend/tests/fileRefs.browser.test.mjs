import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const instrument = { name: 'file-refs-fixture', enforce: 'pre', transform(source, id) {
  if (id.endsWith('/src/views/ChatView.vue')) return source.replace('</script>', 'defineExpose({ items, artifactStage, inputAttachments, messageInput, modelsFetched })\n</script>')
} }
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)), plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/fileRefs.ts', import.meta.url)), name: 'FileRefsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const files = [
  { path: 'resize_batch.py', name: 'resize_batch.py', mime: 'text/x-python', subtitle: 'Python', size: 120 },
  { path: 'report.md', name: 'report.md', mime: 'text/markdown', subtitle: 'Markdown', size: 50 },
  { path: 'crop_log.csv', name: 'crop_log.csv', mime: 'text/csv', subtitle: '2 rows', size: 48 },
  { path: 'exports/hero.zip', name: 'hero.zip', mime: 'application/zip', subtitle: '2 files', size: 1000 },
  { path: 'hero.png', name: 'hero.png', mime: 'image/png', size: 68 },
  { path: 'manifest.json', name: 'manifest.json', mime: 'application/json', size: 40 },
  { path: 'unknown.bin', name: 'unknown.bin', mime: 'application/octet-stream', size: 10 },
].map(file => ({ root: 'chat', ...file }))
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=', 'base64')

for (const phone of [false, true]) test(`file refs stage and round trip (${phone ? 'phone' : 'desktop'})`, async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: phone ? { width: 390, height: 844 } : { width: 1280, height: 900 }, isMobile: phone, hasTouch: phone })
  const errors = [], requests = [], sent = []
  let modified = 1, missing = false, largeTable = false
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), path = url.pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app" style="height:100dvh"></div></body></html>' })
    if (path.includes('/files/')) {
      requests.push(url.href)
      const file = files.find(f => f.path === url.searchParams.get('path')) || files[0]
      if (path.endsWith('/info')) return missing && file.name === 'unknown.bin' ? route.fulfill({ status: 404 }) : route.fulfill({ json: { ...file, modified_ns: modified } })
      if (path.endsWith('/index')) return route.fulfill({ json: { entries: [
        { path: 'out/hero.png', name: 'hero.png', mime: 'image/png', size: 68, directory: false },
        { path: 'out/notes.md', name: 'notes.md', mime: 'text/markdown', size: 10, directory: false },
      ] } })
      if (path.endsWith('/attach')) return route.fulfill({ json: { root: 'chat', path: 'attachments/notes.md', filename: 'notes.md' } })
      if (path.endsWith('/save')) return route.fulfill({ json: { asset_id: 1, media_id: 1 } })
      const name = url.searchParams.get('entry') || file.name
      if (name.endsWith('.png')) return route.fulfill({ contentType: 'image/png', body: png })
      const text = name.endsWith('.py') ? `from pathlib import Path\nprint("resize images ${modified}")` : name.endsWith('.csv') ? (largeTable ? 'name,count\n' + Array.from({ length: 5000 }, (_, i) => `row${i},${i}`).join('\n') : 'name,count\n"hero, one",42\nsecond,12\n') : name.endsWith('.json') ? '{"images":{"count":42}}' : '# Report\nAll images resized.'
      return route.fulfill({ contentType: 'text/plain', body: text })
    }
    if (path === '/api/chats/1') return route.fulfill({ json: { id: 1, name: 'File refs', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    if (path.endsWith('/items')) {
      if (route.request().method() === 'POST') sent.push(route.request().postDataJSON())
      return route.fulfill({ json: { items: [], has_more: false } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    if (path === '/api/assets/9/revisions') return route.fulfill({ json: { asset: { id: 9, title: 'Saved report', current_revision_id: 91 }, revisions: [{ id: 91, revision_number: 1, media_id: 99, file_format: 'md' }] } })
    if (path.endsWith('/content')) return route.fulfill({ json: { content: '# Saved markdown', images: [] } })
    if (path.includes('/media/')) return route.fulfill({ contentType: 'text/plain', body: '# Saved markdown' })
    return route.fulfill({ json: {} })
  })
  await page.goto(`http://file-refs.test/${phone ? '?viewport=compact&pointer=coarse' : ''}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.fileRefsTest?.modelsFetched)).toBe(true)
  await page.evaluate(files => { window.fileRefsTest.items = [
    { id: 1, item_type: 'assistant_message', message_text: 'Done. I resized the images and wrote a report.' },
    { id: 2, item_type: 'file_display', item_metadata: { files } },
  ] }, files)
  const chip = name => page.getByRole('button').filter({ has: page.locator('span', { hasText: name }) }).filter({ hasNot: page.locator('button') }).first()
  const close = () => page.getByRole('button', { name: 'Close stage', exact: true }).click()
  await chip('resize_batch.py').click()
  await expect(page.locator('.cm-content')).toContainText('resize images')
  await expect(page.getByText('Set as latest', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: `/tmp/file-refs-${phone ? 'phone' : 'desktop'}-code.png` })
  modified = 2
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.locator('.cm-content')).toContainText('resize images 2')
  await close()
  await chip('report.md').click()
  await expect(page.getByRole('heading', { name: 'Report', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('.cm-content')).toContainText('# Report')
  await close()
  await chip('crop_log.csv').click()
  await expect(page.getByRole('cell', { name: 'hero, one', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '42', exact: true })).toBeVisible()
  largeTable = true; modified++
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByText('5000 rows', { exact: true })).toBeVisible()
  await page.locator('table').locator('..').evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(page.getByRole('cell', { name: 'row4999', exact: true })).toBeVisible()
  assert.ok(await page.locator('tbody tr').count() <= 102, 'Large tables render a bounded row window')
  largeTable = false
  await close()
  await chip('hero.zip').click()
  await page.getByRole('button', { name: '▸ out', exact: true }).click()
  await page.getByRole('button', { name: 'hero.png 68 B', exact: true }).click()
  await expect.poll(() => page.locator('img[alt="hero.png"]').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true)
  await page.getByRole('button', { name: 'notes.md 10 B', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Report', exact: true })).toBeVisible()
  await page.screenshot({ path: `/tmp/file-refs-${phone ? 'phone' : 'desktop'}-zip.png` })
  await page.getByRole('button', { name: 'Attach to reply', exact: true }).last().click()
  await expect.poll(() => page.evaluate(() => window.fileRefsTest.inputAttachments.length)).toBe(1)
  await page.getByRole('button', { name: 'Save to library', exact: true }).last().click()
  await close()
  await expect(page.locator('.chat-attachments')).toContainText('notes.md')
  await chip('manifest.json').click()
  await expect(page.locator('summary').filter({ hasText: 'images:' })).toBeVisible()
  await close()
  await chip('unknown.bin').click()
  await expect(page.getByText('10 B · application/octet-stream', { exact: true })).toBeVisible()
  await expect(page.locator('img[alt="unknown.bin"]')).toHaveCount(0)
  await close()
  await page.getByPlaceholder('Type a message...').fill('Fix this file')
  await page.getByPlaceholder('Type a message...').press('Enter')
  await expect.poll(() => sent.length).toBe(1)
  assert.equal(sent[0].attachments[0].workspace_ref.path, 'attachments/notes.md')
  assert.equal(requests.some(url => url.includes('/content') && url.includes('hero.zip') && !url.includes('entry=')), false, 'ZIP archive is never downloaded for preview')
  await page.evaluate(() => window.fileRefsTest.items.push({ id: 3, item_type: 'media_display', item_metadata: { display_data: { artifact: { asset_id: 9, revision_id: 91, revision_number: 1 } } } }))
  await expect(page.getByRole('heading', { name: 'Saved markdown', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'v1', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('.cm-content')).toContainText('# Saved markdown')
  await close()
  if (phone) {
    await page.getByRole('button', { name: 'File actions', exact: true }).first().click()
    await expect(page.locator('[data-sheet-layer]')).toBeVisible()
    await page.mouse.click(10, 10)
    await expect(page.locator('[data-sheet-layer]')).toHaveCount(0)
  }
  missing = true
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(chip('unknown.bin')).toBeDisabled()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, 'No horizontal page overflow')
  assert.deepEqual(errors, [])
})
