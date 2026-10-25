import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'
const result = await build({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), logLevel: 'silent', plugins: [vue()],
  define: { 'process.env.NODE_ENV': '"production"' }, css: { postcss: { plugins: [] } },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/editorTouch.ts', import.meta.url)), formats: ['iife'], name: 'EditorTouchTest',
  } },
})
const script = (Array.isArray(result) ? result : [result]).flatMap(r => r.output).find(x => x.type === 'chunk').code
async function fixture(t, options = {}) {
  const browser = await chromium.launch(); t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, ...options })
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  t.after(() => assert.deepEqual(errors, []))
  await page.route('http://editor.test/**', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://editor.test/')
  await page.addScriptTag({ content: script })
  assert.deepEqual(errors, [], 'fixture script errors')
  return page
}
async function dragTouch(page, from, to) {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: from[0], y: from[1], id: 1 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: to[0], y: to[1], id: 1 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await cdp.detach()
}
test('drawer family switches preserve one panel and remove previous controls', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.switchFamily = window.editorTouch.mountDrawer() })
  for (const family of ['Retouch', 'Paint', '', 'Crop', '', 'Adjust', '']) {
    await page.evaluate(name => window.switchFamily(name), family)
    assert.equal(await page.locator('#family').count(), family ? 1 : 0)
    assert.equal(await page.locator('#test-drawer-panels #properties').count(), 1)
    assert.equal(await page.locator('#test-drawer-body').innerText(), family ? `${family}\nEdits` : 'Edits')
  }
})
async function swipeTouch(page, x, y0, y1, steps = 10) {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: y0, id: 1 }] })
  for (let i = 1; i <= steps; i++) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y0 + (y1 - y0) * i / steps, id: 1 }] })
    await page.waitForTimeout(30)
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await cdp.detach()
}
test('dragging the drawer body moves the drawer, not just its content', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.switchFamily = window.editorTouch.mountDrawer() })
  const drawer = page.locator('.tool-drawer')
  assert.equal(await drawer.getAttribute('data-level'), 'half')
  const body = await page.locator('#test-drawer-body').boundingBox()
  await swipeTouch(page, 200, body.y + 40, body.y - 260)
  assert.equal(await drawer.getAttribute('data-level'), 'full')
  const full = await page.locator('#test-drawer-body').boundingBox()
  await swipeTouch(page, 200, full.y + 20, full.y + 600)
  assert.equal(await drawer.getAttribute('data-level'), 'collapsed')
})
test('annotation rectangle follows a finger and finishes once', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.annotationTest = window.editorTouch.mountAnnotation() })
  await dragTouch(page, [50, 50], [160, 180])
  const result = await page.evaluate(() => ({ state: window.annotationTest.state(), history: window.annotationTest.history() }))
  assert.equal(result.state.annotations.length, 1)
  assert.equal(result.state.annotations[0].type, 'rectangle')
  assert.ok(result.state.annotations[0].width > 0.3)
  assert.ok(result.state.annotations[0].height > 0.3)
  assert.equal(result.history.length, 1)
})
test('color spectrum responds throughout a finger drag', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.colorState = window.editorTouch.mountColor() })
  await page.getByRole('button', { name: 'Spectrum', exact: true }).click()
  const spectrum = page.locator('[class*="cursor-crosshair"]')
  await spectrum.evaluate(el => { el.style.height = '150px'; el.style.touchAction = 'none' })
  const box = await spectrum.boundingBox()
  await dragTouch(page, [box.x + 20, box.y + 60], [box.x + 200, box.y + 90])
  const color = await page.evaluate(() => window.colorState())
  assert.notDeepEqual(color, { r: 255, g: 0, b: 0 })
  assert.ok(color.b > color.r, 'dragging into the cyan/blue part changes hue')
})

test('color picker initializes its spectrum from a nonwhite color', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.editorTouch.mountColor({ r: 0, g: 0, b: 255 }))
  await page.getByRole('button', { name: 'Spectrum', exact: true }).click()
  const left = await page.locator('[class*="cursor-crosshair"] > div').evaluate(el => parseFloat(el.style.left))
  assert.ok(Math.abs(left - 100 * 2 / 3) < 0.01)
})

test('Escape dismisses the picker without reaching editor shortcuts', async t => {
  const page = await fixture(t)
  await page.evaluate(() => {
    window.editorTouch.mountPopover()
    window.escaped = false
    window.addEventListener('keydown', e => { if (e.key === 'Escape') window.escaped = true })
  })
  await page.getByRole('button', { name: 'Brush' }).click()
  assert.equal(await page.locator('.editor-picker').count(), 1)
  await page.keyboard.press('Escape')
  assert.equal(await page.locator('.editor-picker').count(), 0)
  assert.equal(await page.evaluate(() => window.escaped), false)
})

test('tapping a numeric control opens its value sheet without focusing text entry', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.editorTouch.mountScrub())
  await page.getByRole('button', { name: '50' }).tap()
  const sheet = page.locator('[data-sheet-layer]')
  assert.equal(await sheet.count(), 1)
  assert.equal(await sheet.locator('input[type=text]').evaluate(el => el === document.activeElement), false)
  await sheet.getByRole('button', { name: 'Increase' }).tap()
  assert.equal(await sheet.locator('input[type=text]').inputValue(), '51')
})

test('a sheet swipes away with a downward flick and springs back from a nudge', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.editorTouch.mountScrub())
  await page.getByRole('button', { name: '50' }).tap()
  // Grab the sheet by its title: the value field keeps its own gestures.
  const handle = await page.locator('[data-sheet-layer] .sheet-panel h2').boundingBox()
  const y = handle.y + handle.height / 2
  await swipeTouch(page, 200, y, y + 20, 2)
  await page.waitForTimeout(400)
  assert.equal(await page.locator('[data-sheet-layer]').count(), 1)
  await swipeTouch(page, 200, y, y + 300)
  await page.waitForTimeout(600)
  assert.equal(await page.locator('[data-sheet-layer]').count(), 0)
})

test('a drag across a numeric control on touch does not change it', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.editorTouch.mountScrub())
  const box = await page.getByRole('button', { name: '50' }).boundingBox()
  await dragTouch(page, [box.x + box.width / 2, box.y + box.height / 2], [box.x + box.width / 2 + 80, box.y + box.height / 2])
  assert.equal(await page.getByRole('button', { name: '50' }).count(), 1)
})

test('crop pinch changes the crop once and renders at device resolution', async t => {
  const page = await fixture(t, { deviceScaleFactor: 3 })
  await page.evaluate(() => { window.cropTest = window.editorTouch.mountCrop() })
  assert.equal(await page.locator('canvas').evaluate(el => el.width), 900)
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 108, y: 158, id: 1 }, { x: 208, y: 158, id: 2 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 78, y: 138, id: 1 }, { x: 238, y: 178, id: 2 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  const result = await page.evaluate(() => ({ crop: window.cropTest.crop(), commits: window.cropTest.commits() }))
  assert.ok(result.crop.width < 0.7)
  assert.ok(result.crop.rotation < -0.2)
  assert.equal(result.commits, 1)
})

test('edit rows select on the first tap and nested controls do not select the row', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.rowEvents = window.editorTouch.mountEditRow() })
  await page.locator('[data-op-id]').click({ position: { x: 5, y: 5 } })
  await page.getByRole('button', { name: 'Hide this edit', exact: true }).click()
  await page.getByRole('button', { name: 'Remove this edit', exact: true }).click()
  assert.deepEqual(await page.evaluate(() => window.rowEvents()), ['select', 'toggle', 'remove'])
})
