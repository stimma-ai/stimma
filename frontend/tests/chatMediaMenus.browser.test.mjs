// The chat's media surfaces (artifact panel, image collections, selection bar)
// give one menu per target, act on what is shown, and keep keys where they belong.
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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatMediaMenus.ts', import.meta.url)), name: 'ChatMediaMenusTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=', 'base64')

const browserItem = (assetId, mediaId) => ({ id: assetId, asset_id: assetId, media_id: mediaId, file_format: 'png', file_hash: `hash-${mediaId}`, width: 64, height: 64, deleted_at: null, has_clip_embedding: false, markers: [], tags: [] })

async function fixture(t, query = '') {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  page.setDefaultTimeout(5000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app"></div></body></html>' })
    if (path.includes('thumbnail') || path.endsWith('/file')) return route.fulfill({ contentType: 'image/png', body: png })
    if (path.includes('/faces')) return route.fulfill({ json: { faces: [] } })
    let match = path.match(/\/assets\/item\/(\d+)\/browser$/)
    // The artifact asset's browser row is its current revision (v3, media 503).
    if (match) return route.fulfill({ json: Number(match[1]) === 50 ? browserItem(50, 503) : browserItem(Number(match[1]), Number(match[1]) - 100) })
    match = path.match(/\/media\/(\d+)$/)
    if (match) return route.fulfill({ json: { id: Number(match[1]), file_format: 'png', file_hash: `hash-${match[1]}`, width: 64, height: 64, filename: `m${match[1]}.png` } })
    if (/markers|boards|projects|tools|chats|flows/.test(path)) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto(`http://chat-media-menus.test/${query}`)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

const menuState = page => page.evaluate(() => {
  const { mediaId, assetId, mediaIds, assetIds, selectedItems, projectId, visible } = window.chatMenus.menu.state.value
  return { visible, mediaId, assetId, mediaIds: [...mediaIds], assetIds: [...assetIds], selected: selectedItems.length, projectId }
})
const menu = page => page.locator('[data-escape-layer]').filter({ has: page.getByRole('button', { name: /^Print/ }) }).first()

test('the artifact image has one menu, and it prints the version on screen', async t => {
  const page = await fixture(t)
  const stage = page.getByTestId('artifact-stage')
  await stage.locator('img[alt="Artifact"]').click({ button: 'right' })
  const fromRightClick = await menuState(page)
  assert.deepEqual(fromRightClick, { visible: true, mediaId: 501, assetId: 50, mediaIds: [501], assetIds: [50], selected: 0, projectId: 7 })
  await page.keyboard.press('Escape')
  await stage.getByRole('button', { name: 'Actions' }).click()
  const fromKebab = await menuState(page)
  assert.deepEqual(fromKebab, fromRightClick)
  await menu(page).getByRole('button', { name: 'Print', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.chatMenus.printed.length)).toBe(1)
  const printed = await page.evaluate(() => window.chatMenus.printed[0])
  assert.match(printed, /media\/501\/file/)
  assert.doesNotMatch(printed, /503/)
})

test('the artifact panel owns its keys only while it has focus and nothing is over it', async t => {
  const page = await fixture(t)
  const stage = page.getByTestId('artifact-stage')
  const viewed = () => page.evaluate(() => window.chatMenus.viewed.value)
  await page.getByRole('textbox', { name: 'Message' }).focus()
  await page.keyboard.press('ArrowRight')
  assert.equal(await viewed(), 1)
  await stage.locator('img[alt="Artifact"]').click()
  assert.deepEqual(await page.evaluate(() => window.chatMenus.events.slideshow), [501])
  await stage.focus()
  await page.keyboard.press('ArrowRight')
  assert.equal(await viewed(), 2)
  await page.keyboard.press('Meta+ArrowLeft')
  assert.equal(await viewed(), 2)
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('ArrowLeft')
  assert.equal(await viewed(), 1)
  // A menu over the page takes Escape; the panel stays.
  await stage.locator('img[alt="Artifact"]').click({ button: 'right' })
  await stage.focus()
  await page.keyboard.press('Escape')
  await expect.poll(() => page.evaluate(() => window.chatMenus.menu.state.value.visible)).toBe(false)
  assert.equal(await page.evaluate(() => window.chatMenus.events.closed), 0)
  await stage.focus()
  await expect(page.locator('[data-context-menu]')).toHaveCount(0)
  await page.keyboard.press('Escape')
  assert.equal(await page.evaluate(() => window.chatMenus.events.closed), 1)
})

test('clicking the artifact video plays it; the slideshow opens from its button', async t => {
  const page = await fixture(t, '?kind=mp4')
  const stage = page.getByTestId('artifact-stage')
  const video = stage.locator('video')
  await expect(video).toBeAttached()
  assert.equal(await video.evaluate(el => el.parentElement.className.includes('cursor-zoom-in')), false)
  await video.click({ position: { x: 50, y: 50 } })
  assert.deepEqual(await page.evaluate(() => window.chatMenus.events.slideshow), [])
  await stage.getByRole('button', { name: 'Open slideshow' }).click()
  assert.deepEqual(await page.evaluate(() => window.chatMenus.events.slideshow), [501])
})

test('a picked image\'s menu acts on every pick, and the selection bar reaches it', async t => {
  const page = await fixture(t, '?surface=collection')
  const collection = page.getByTestId('media-collection')
  await collection.getByRole('checkbox', { name: 'Select image 1' }).click({ force: true })
  await collection.getByRole('checkbox', { name: 'Select image 3' }).click({ force: true })
  const tile = n => collection.locator(`[data-tile="${n}"]`).first()
  await tile(2).click({ button: 'right' })
  assert.deepEqual(await menuState(page), { visible: true, mediaId: 103, assetId: 203, mediaIds: [101, 103], assetIds: [201, 203], selected: 2, projectId: 7 })
  await page.keyboard.press('Escape')
  await tile(1).click({ button: 'right' })
  assert.deepEqual(await menuState(page), { visible: true, mediaId: 102, assetId: 202, mediaIds: [102], assetIds: [202], selected: 1, projectId: 7 })
  await page.keyboard.press('Escape')
  await page.getByTestId('media-selection-bar').getByRole('button', { name: 'More actions' }).click()
  assert.deepEqual(await menuState(page), { visible: true, mediaId: 101, assetId: 201, mediaIds: [101, 103], assetIds: [201, 203], selected: 2, projectId: 7 })
  await menu(page).getByRole('button', { name: 'Print 2' }).click()
  await expect.poll(() => page.evaluate(() => window.chatMenus.printed.length)).toBe(1)
  assert.equal((await page.evaluate(() => window.chatMenus.printed[0])).match(/<img /g).length, 2)
})

test('a picked hero opens the picks\' menu', async t => {
  const page = await fixture(t, '?surface=collection&view=preview')
  const hero = page.getByTestId('media-collection-hero')
  await hero.getByRole('checkbox', { name: 'Select this image' }).click({ force: true })
  await page.getByTestId('media-collection').locator('[data-tile="1"]').click({ modifiers: ['Control'] })
  await hero.locator('img').first().click({ button: 'right' })
  assert.deepEqual((await menuState(page)).mediaIds, [101, 102])
  await page.keyboard.press('Escape')
  await hero.getByRole('button', { name: 'More actions' }).click()
  assert.deepEqual((await menuState(page)).mediaIds, [101, 102])
})

test('collection keys stay with the control that has focus', async t => {
  const page = await fixture(t, '?surface=collection&count=20&view=preview')
  const collection = page.getByTestId('media-collection')
  const active = () => collection.locator('[aria-current="true"]').getAttribute('aria-label')
  await collection.locator('[data-tile="15"]').click()
  assert.equal(await active(), 'Image 16 of 20')
  // Arrows on the view toggle are the toggle's, not the picture's.
  await collection.getByRole('radio', { name: 'Preview' }).focus()
  await page.keyboard.press('ArrowLeft')
  assert.equal(await active(), 'Image 16 of 20')
  // Back to a collapsed grid that does not show image 16: a shown tile takes Tab.
  await collection.getByRole('radio', { name: 'Grid' }).click()
  const tabbable = collection.locator('[data-tile][tabindex="0"]')
  await expect(tabbable).toHaveCount(1)
  await expect(tabbable).toBeVisible()
  // "+N" expands on Enter instead of opening the image under it.
  const overflow = collection.getByRole('button', { name: 'Show all 20 images' })
  await overflow.focus()
  await page.keyboard.press('Enter')
  await expect(collection.locator('[data-tile="19"]')).toBeVisible()
  assert.equal(await collection.getByRole('radio', { name: 'Grid' }).getAttribute('aria-checked'), 'true')
})
