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
async function fixture(t) {
  const browser = await chromium.launch(); t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true })
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

test('tapping a numeric control opens its slider without focusing text entry', async t => {
  const page = await fixture(t)
  await page.evaluate(() => window.editorTouch.mountScrub())
  await page.getByRole('button', { name: '50' }).tap()
  assert.equal(await page.locator('.editor-picker').count(), 1)
  assert.equal(await page.locator('.editor-picker input[type=text]').evaluate(el => el === document.activeElement), false)
})
