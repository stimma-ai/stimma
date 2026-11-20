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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/slideshowKeyboard.ts', import.meta.url)), name: 'SlideshowKeyboardTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t, { chat = false, nav = false, kinds = null, routes = null, items = null, containerType = null } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/api/**', route => route.fulfill({ json: [] }))
  if (chat || nav) {
    await page.route('**/api/markers', route => route.fulfill({ json: [
      { id: 1, name: 'Keep', color: '#ffffff', icon_svg: '<svg></svg>' },
    ] }))
  }
  await page.route('http://slideshow-keyboard.test/', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://slideshow-keyboard.test/')
  if (chat) await page.evaluate(() => { window.slideshowChatTest = true })
  if (nav) await page.evaluate(() => { window.slideshowNavTest = true })
  if (kinds) await page.evaluate(list => { window.slideshowKinds = list }, kinds)
  if (items) await page.evaluate(list => { window.slideshowItems = list }, items)
  if (containerType) await page.evaluate(type => { window.slideshowContainerType = type }, containerType)
  if (routes) await routes(page)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

test('contact sheets scroll with the wheel in slideshow while images still zoom', async t => {
  const html = Array.from({ length: 80 }, (_, i) => `<p>Sheet row ${i + 1}</p>`).join('')
  const page = await fixture(t, { kinds: ['stimmasheet.html', 'png'], routes: page =>
    page.route('**/media/1/content', route => route.fulfill({ json: { html } })),
  })
  const document = page.locator('[data-sheet-scope]')
  await expect(document.getByText('Sheet row 1', { exact: true })).toBeVisible()
  const scroller = document.locator('..')
  const viewer = scroller.locator('../..')
  const transform = await viewer.evaluate(el => getComputedStyle(el).transform)
  const box = await scroller.boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, 500)
  await expect.poll(() => scroller.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
  const down = await scroller.evaluate(el => el.scrollTop)
  await page.mouse.wheel(0, -200)
  await expect.poll(() => scroller.evaluate(el => el.scrollTop)).toBeLessThan(down)
  assert.equal(await viewer.evaluate(el => getComputedStyle(el).transform), transform)

  await page.keyboard.press('ArrowRight')
  const image = page.locator('img[src*="kind-2"]').first()
  await expect(image).toBeVisible()
  const before = await image.evaluate(el => el.getBoundingClientRect().width)
  await image.hover()
  await page.mouse.wheel(0, -200)
  await expect.poll(() => image.evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThan(before)
})

test('a completed chat video retains its info and marker strip while its page reloads', async t => {
  const page = await fixture(t, { chat: true })
  const video = page.locator('video').first()
  const panel = page.getByTestId('media-info-panel')
  const marker = page.locator('.slideshow-control-bar').getByTitle('Add Keep', { exact: true })
  await expect(video).toHaveAttribute('src', /finished-video/)
  await expect(panel.getByRole('button', { name: 'More actions', exact: true }).first()).toBeVisible()
  await expect(marker).toBeVisible()
  await page.evaluate(() => window.slideshowKeys.refreshChat())
  // Flush the collection watcher while the replacement page remains unresolved.
  await expect(page.locator('.scroll-container [title="Loading..."]').first()).toBeAttached()
  await expect(video).toHaveAttribute('src', /finished-video/)
  await expect(panel.getByRole('button', { name: 'More actions', exact: true }).first()).toBeVisible()
  await expect(marker).toBeVisible()
  await page.evaluate(() => window.slideshowKeys.finishRefresh())
  await expect(page.locator('.scroll-container [title="Loading..."]')).toHaveCount(0)
  await expect(marker).toBeVisible()
})

test('after stepping to an image that is still loading, nothing acts on the one left behind', async t => {
  const page = await fixture(t, { nav: true })
  const deletes = []
  await page.route('**/api/**', route => {
    if (route.request().method() === 'DELETE' || /trash|delete/.test(route.request().url())) deletes.push(route.request().url())
    return route.fallback()
  })
  const marker = page.locator('.slideshow-control-bar').getByTitle('Add Keep', { exact: true })
  const image = page.locator('img[src*="still-31"]').first()
  await expect(image).toBeVisible()
  await expect(marker).toBeVisible()
  // Reload the chat's page and hold it: the first image stays up with its controls.
  await page.evaluate(() => window.slideshowKeys.refreshChat())
  await expect(page.locator('.scroll-container [title="Loading..."]').first()).toBeAttached()
  await expect(marker).toBeVisible()
  // Step on while the page is still out: the old picture stays up, its actions do not.
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
  await expect(image).toBeVisible()
  await expect(marker).toHaveCount(0)
  await page.keyboard.press('Delete')
  await page.keyboard.press('Backspace')
  assert.deepEqual(deletes, [])
  await page.evaluate(() => window.slideshowKeys.finishRefresh())
  await expect(page.locator('img[src*="still-32"]').first()).toBeVisible()
  await expect(marker).toBeVisible()
})

test('chorded keys go to the browser, and Backspace trashes like Delete', async t => {
  const page = await fixture(t, { nav: true })
  const deletes = []
  await page.route('**/api/**', route => {
    if (route.request().method() === 'DELETE' || /trash|delete/.test(route.request().url())) deletes.push(route.request().url())
    return route.fallback()
  })
  await expect(page.locator('img[src*="still-31"]').first()).toBeVisible()
  for (const key of ['Control+d', 'Meta+d', 'Alt+d', 'Meta+ArrowRight', 'Control+f', 'Meta+f', 'Meta+i', 'Meta+a']) await page.keyboard.press(key)
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await expect(page.locator('body')).not.toHaveClass(/slideshow-focus-mode/)
  await expect(page.getByTestId('media-info-panel')).toBeVisible()
  await page.keyboard.press('d')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
  await expect(page.locator('img[src*="still-32"]').first()).toBeVisible()
  await page.keyboard.press('Backspace')
  await expect.poll(() => deletes.length).toBe(1)
  assert.match(deletes[0], /32/)
})

test('every media kind answers a right-click with its menu', async t => {
  const page = await fixture(t, { kinds: ['md', 'mp3', 'svg'] })
  const stage = page.locator('[data-escape-layer][data-drop-zone]')
  const menuFor = () => page.evaluate(() => {
    const { visible, mediaId } = window.slideshowKeys.menu.state.value
    return visible ? mediaId : null
  })
  const centre = async () => {
    const box = await stage.boundingBox()
    await page.mouse.click(box.x + box.width / 2 - 120, box.y + box.height / 2, { button: 'right' })
  }
  for (const [index, id] of [[0, 1], [1, 2], [2, 3]]) {
    await expect(page.locator('[data-current-index]')).toHaveText(String(index))
    await page.waitForTimeout(200)
    await centre()
    await expect.poll(menuFor).toBe(id)
    await page.keyboard.press('Escape')
    await expect.poll(menuFor).toBe(null)
    await expect(page.locator('[data-context-menu]')).toHaveCount(0)
    await stage.focus()
    if (index < 2) await page.keyboard.press('ArrowRight')
  }
})

test('a click into a layout keeps ←/→ and the menu with the slideshow, but not from its controls', async t => {
  const layout = '<html data-stimma-width="400" data-stimma-height="300"><body style="margin:0;height:300px"><p>Layout copy</p><input aria-label="Field"><button>Inside</button></body></html>'
  const page = await fixture(t, { kinds: ['stimmalayout', 'png'], routes: page => page.route('**/layout-html', route => route.fulfill({ contentType: 'text/html', body: layout })) })
  const frame = page.frameLocator('iframe')
  await frame.getByText('Layout copy').click()
  await frame.getByRole('textbox', { name: 'Field' }).focus()
  await page.keyboard.press('ArrowRight')
  await frame.getByRole('button', { name: 'Inside' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await frame.locator('body').click({ button: 'right', position: { x: 300, y: 250 } })
  await expect.poll(() => page.evaluate(() => window.slideshowKeys.menu.state.value.visible && window.slideshowKeys.menu.state.value.mediaId)).toBe(1)
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-context-menu]')).toHaveCount(0)
  await frame.locator('body').click({ position: { x: 300, y: 250 } })
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
})

test('Slideshow owns navigation, playback and viewer keys while a Modal blocks both viewer and grid', async t => {
  const page = await fixture(t)
  const viewer = page.locator('[data-escape-layer][data-drop-zone]')
  await expect(viewer).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
  await page.keyboard.press('ArrowLeft')
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await page.keyboard.press('Space')
  await expect(page.getByTitle('Pause (space)', { exact: true })).toBeVisible()
  await page.keyboard.press('Space')
  await expect(page.getByTitle('Play slideshow (space)', { exact: true })).toBeVisible()
  await page.keyboard.press('f')
  await expect(page.locator('body')).toHaveClass(/slideshow-focus-mode/)
  await page.keyboard.press('f')
  await expect(page.locator('body')).not.toHaveClass(/slideshow-focus-mode/)
  assert.deepEqual(await page.evaluate(() => window.slideshowKeys.grid), [])
  await page.evaluate(() => window.slideshowKeys.modal())
  await expect(page.getByRole('dialog')).toBeFocused()
  for (const key of ['ArrowRight', 'Space', 'f', 'Delete', 'Control+a']) await page.keyboard.press(key)
  await expect(page.locator('[data-current-index]')).toHaveText('0')
  await expect(page.getByTitle('Play slideshow (space)', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toHaveClass(/slideshow-focus-mode/)
  assert.deepEqual(await page.evaluate(() => window.slideshowKeys.grid), [])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-current-index]')).toHaveText('1')
})

const slide = (id, hash, assetId) => ({ id, media_id: id, asset_id: assetId, file_format: 'png', file_hash: hash, width: 32, height: 32 })

test('Delete inside a set trashes a linked member, removes an embedded one, and never parks on a broken image', async t => {
  const calls = []
  const setItem = { id: 50, asset_id: 50, media_id: 1, file_format: 'stimmaset.json', file_hash: 'set-1', width: 0, height: 0 }
  const page = await fixture(t, { items: [setItem], routes: async page => {
    await page.route('**/media/1/content', route => route.fulfill({ json: { version: 1, items: [
      { member_id: 11, resolved: slide(101, 'member-a', 201) },
      { member_id: 12, resolved: slide(102, 'member-b', null) },
      { member_id: 13, resolved: slide(103, 'member-c', 203) },
    ] } }))
    await page.route('**/media/2/content', route => route.fulfill({ json: { version: 1, items: [
      { member_id: 23, resolved: slide(103, 'member-c', 203) },
    ] } }))
    await page.route('**/assets/batch/trash', route => { calls.push(['trash', route.request().postDataJSON()]); return route.fulfill({ json: { asset_ids: [201] } }) })
    await page.route('**/assets/item/50/container-members/12/remove', route => { calls.push(['remove', 12]); return route.fulfill({ json: { asset_id: 50, revision_id: 2, media_id: 2, previous_revision_id: 1 } }) })
    await page.route('**/media/102', route => { calls.push(['delete-media', 102]); return route.fulfill({ status: 409, json: {} }) })
  } })
  await page.locator('img[src*="member-a"]').first().click()
  await expect(page.getByTitle('Exit set and return to main slideshow')).toBeVisible()
  await expect(page.locator('img[src*="member-a"]').first()).toBeVisible()

  await page.keyboard.press('Delete')
  await expect.poll(() => calls.length).toBe(1)
  assert.deepEqual(calls[0], ['trash', { asset_ids: [201] }])
  await expect(page.locator('img[src*="member-a"]')).toHaveCount(0)
  await expect(page.locator('img[src*="member-b"]').first()).toBeVisible()
  await expect(page.getByText('Image no longer available')).toHaveCount(0)

  // An embedded member exists only in the set: Delete takes it out of the set.
  await page.keyboard.press('Delete')
  await expect.poll(() => calls.length).toBe(2)
  assert.deepEqual(calls[1], ['remove', 12])
  await expect(page.locator('img[src*="member-c"]').first()).toBeVisible()
  await expect(page.locator('img[src*="member-b"]')).toHaveCount(0)
})

test('Delete does nothing to the parts of a contact sheet', async t => {
  const deletes = []
  const page = await fixture(t, { items: [slide(7, 'sheet-part', 70)], containerType: 'sheet' })
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') deletes.push(route.request().url())
    return route.fallback()
  })
  const image = page.locator('img[src*="sheet-part"]').first()
  await expect(image).toBeVisible()
  await page.keyboard.press('Delete')
  await page.keyboard.press('Backspace')
  await image.click({ button: 'right' })
  const memberOf = await page.evaluate(() => window.slideshowKeys.menu.state.value.memberOf)
  assert.equal(memberOf?.type, 'sheet')
  await expect(page.getByText('Move to trash')).toHaveCount(0)
  assert.deepEqual(deletes, [])
})

test('an open slideshow keeps the screen awake and hides the idle cursor outside focus mode', async t => {
  const page = await fixture(t, { routes: page => page.evaluate(() => {
    window.wakeLockLog = []
    Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: {
      async request(type) {
        window.wakeLockLog.push(`request:${type}`)
        return { async release() { window.wakeLockLog.push('release') }, addEventListener() {} }
      },
    } })
  }) })
  await expect(page.locator('.slideshow-control-bar')).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.wakeLockLog)).toEqual(['request:screen'])
  // Opened without moving the mouse: the cursor still hides.
  await expect.poll(() => page.evaluate(() => document.body.classList.contains('slideshow-cursor-hidden')), { timeout: 5000 }).toBe(true)
  await page.mouse.move(400, 300)
  await page.mouse.move(410, 310)
  assert.equal(await page.evaluate(() => document.body.classList.contains('slideshow-cursor-hidden')), false)
  await expect.poll(() => page.evaluate(() => document.body.classList.contains('slideshow-cursor-hidden')), { timeout: 5000 }).toBe(true)
  await page.mouse.move(420, 320)
  assert.equal(await page.evaluate(() => document.body.classList.contains('slideshow-cursor-hidden')), false)
})
