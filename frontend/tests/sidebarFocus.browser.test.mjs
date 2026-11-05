import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium } from '@playwright/test'

const built = await build({ configFile: false, logLevel: 'error', define: { 'process.env.NODE_ENV': '"production"' },
  build: { write: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/sidebarFocus.ts', import.meta.url)), name: 'SidebarFocusTest', formats: ['iife'],
  } },
})
const code = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } })
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html><body><div id="a" style="width:300px;height:300px"></div></body></html>' }))
  await page.goto('http://focus.test/')
  await page.evaluate(() => localStorage.setItem('profileId', 'p1'))
  await page.addScriptTag({ content: code })
  await page.evaluate(() => {
    window.stop = window.sidebarFocus.installDragPeek()
    window.drag = (type, { media = true, files = false, prevent = false, x = 100, y = 100, related = null } = {}) => {
      const dataTransfer = new DataTransfer()
      if (media) dataTransfer.setData('application/x-media-id', '7')
      const target = document.getElementById('a')
      if (prevent) target.addEventListener(type, e => e.preventDefault(), { once: true })
      target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer, clientX: x, clientY: y, relatedTarget: related }))
    }
    window.frame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  })
  return page
}

const peek = page => page.evaluate(() => window.sidebarFocus.dragPeek.value)

test('a media drag reveals the sidebar on the next frame, never inside dragstart', async t => {
  const page = await fixture(t)
  const during = await page.evaluate(() => { window.drag('dragstart'); return window.sidebarFocus.dragPeek.value })
  assert.equal(during, false)
  await page.evaluate(() => window.frame())
  assert.equal(await peek(page), true)
})

test('dragend, drop and leaving the window each end the reveal', async t => {
  const page = await fixture(t)
  for (const end of [
    () => window.drag('dragend'),
    () => window.drag('drop'),
    () => window.drag('dragleave', { x: -2, y: 200 }),
  ]) {
    await page.evaluate(() => { window.drag('dragstart'); return window.frame() })
    assert.equal(await peek(page), true)
    await page.evaluate(`(${end})()`)
    await page.evaluate(() => window.frame())
    assert.equal(await peek(page), false)
  }
})

test('leaving one element for another inside the window keeps the reveal', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.drag('dragstart'); return window.frame() })
  await page.evaluate(() => window.drag('dragleave', { x: 120, y: 200, related: document.body }))
  await page.evaluate(() => window.frame())
  assert.equal(await peek(page), true)
})

test('an end event that lands before the frame wins over the pending reveal', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.drag('dragstart'); window.drag('dragend'); return window.frame() })
  assert.equal(await peek(page), false)
})

test('a pointer move with no button down ends a reveal whose dragend never arrived', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.drag('dragstart'); return window.frame() })
  await page.mouse.move(50, 50)
  await page.evaluate(() => window.frame())
  assert.equal(await peek(page), false)
})

test('native file drags, plain files and cancelled drags do not reveal it', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.drag('dragstart', { prevent: true }); return window.frame() })
  assert.equal(await peek(page), false)
  await page.evaluate(() => { window.drag('dragenter', { media: false }); return window.frame() })
  assert.equal(await peek(page), false)
})

test('a media drag arriving from another window reveals it', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.drag('dragenter'); return window.frame() })
  assert.equal(await peek(page), true)
})

test('the reveal is never stored, the choice is, per profile', async t => {
  const page = await fixture(t)
  await page.evaluate(() => { window.drag('dragstart'); return window.frame() })
  assert.equal(await page.evaluate(() => Object.keys(localStorage).filter(k => k.includes('focus_open')).length), 0)
  assert.equal(await page.evaluate(() => window.sidebarFocus.focusSidebarOpen()), false)
  await page.evaluate(() => window.sidebarFocus.setFocusSidebarOpen(true))
  const stored = await page.evaluate(() => Object.entries(localStorage).filter(([k]) => k.includes('focus_open')))
  assert.equal(stored.length, 1)
  assert.match(stored[0][0], /p1_sidebar_focus_open$/)
  assert.equal(stored[0][1], '1')
  await page.evaluate(() => window.sidebarFocus.setFocusSidebarOpen(false))
  assert.equal(await page.evaluate(() => localStorage.getItem(Object.keys(localStorage).find(k => k.includes('focus_open')))), '0')
})
