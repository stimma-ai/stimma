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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/uiEdgeCases.ts', import.meta.url)), name: 'UiEdgeCasesTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t, uiCase, routes = null) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 800, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/api/**', route => route.fulfill({ json: [] }))
  if (routes) await routes(page)
  await page.route('http://ui-edge-cases.test/', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://ui-edge-cases.test/')
  await page.evaluate(name => { window.uiCase = name }, uiCase)
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

test('agent timers round the whole duration before splitting hours and minutes', async t => {
  const page = await fixture(t, 'timers')
  await expect(page.getByText('Checks back every 2 h', { exact: true })).toBeVisible()
  await expect(page.getByText('Checks back every 1 h', { exact: true })).toBeVisible()
})

test('two drags of the same slider are two undo steps', async t => {
  const page = await fixture(t, 'stack')
  const steps = await page.evaluate(() => {
    const { stack } = window.uiState
    stack.setParams('op1', { exposure: 10 }, 'adjust:exposure')
    stack.setParams('op1', { exposure: 20 }, 'adjust:exposure')
    stack.breakCoalescing()
    stack.setParams('op1', { exposure: 30 }, 'adjust:exposure')
    stack.setParams('op1', { exposure: 40 }, 'adjust:exposure')
    return stack.journal.value.map(entry => [entry.inverse.params.exposure, entry.forward.params.exposure])
  })
  // Each drag undoes to where it started.
  assert.deepEqual(steps, [[0, 20], [20, 40]])
})

test('shift-click across a page that never loaded selects the whole range', async t => {
  const page = await fixture(t, 'grid')
  await page.getByTestId('media-grid-item-1').click()
  // Jump past page 1 (items 201-400) so it is never scrolled into view.
  await page.locator('.media-grid-container').evaluate(el => { el.scrollTop = el.scrollHeight })
  const last = page.getByTestId('media-grid-item-600')
  await expect(last).toBeVisible()
  assert.ok(!(await page.evaluate(() => window.uiState.pages)).includes(1))
  await last.click({ modifiers: ['Shift'] })
  await expect.poll(() => page.evaluate(() => window.uiState.ranges.length)).toBe(1)
  const ids = await page.evaluate(() => window.uiState.ranges[0].ids)
  assert.equal(ids.length, 600)
  assert.deepEqual([ids[0], ids[599]], [1, 600])
})

test('the drawer follows its parent when the space around it changes', async t => {
  const page = await fixture(t, 'drawer')
  const drawer = page.locator('[data-parent] > :last-child')
  await expect.poll(() => drawer.evaluate(el => el.getBoundingClientRect().height)).toBe(600)
  // The keyboard comes up: the column shrinks while the drawer stays full.
  await page.evaluate(() => window.uiState.setHeight(400))
  await expect.poll(() => drawer.evaluate(el => el.getBoundingClientRect().height)).toBe(300)
  await page.evaluate(() => window.uiState.setHeight(750))
  await expect.poll(() => drawer.evaluate(el => el.getBoundingClientRect().height)).toBe(650)
})

test('the lineage screen leaves shortcuts and focused buttons alone', async t => {
  const page = await fixture(t, 'lineage', page =>
    page.route('**/lineage/tree', route => route.fulfill({ json: { nodes: [{ id: 1, file_hash: 'n1', file_format: 'png' }], edges: [] } })))
  await page.waitForTimeout(200)
  const prevented = combo => page.evaluate(([key, ctrl, meta]) => {
    const event = new KeyboardEvent('keydown', { key, ctrlKey: ctrl, metaKey: meta, bubbles: true, cancelable: true })
    document.querySelector('[data-test-button]').dispatchEvent(event)
    return event.defaultPrevented
  }, combo)
  assert.equal(await prevented(['w', true, false]), false)
  assert.equal(await prevented(['w', false, true]), false)
  assert.equal(await prevented(['Enter', false, false]), false)
  // Plain arrow keys still drive the tree.
  assert.equal(await prevented(['ArrowRight', false, false]), true)
})

test('after a prepend that leaves the slide in place, the next step still centers the filmstrip', async t => {
  const page = await fixture(t, 'filmstrip')
  const strip = page.locator('.scroll-container')
  await strip.evaluate(el => { el.scrollLeft = 1000 })
  await page.waitForTimeout(100)
  await page.evaluate(() => window.uiState.prepend(2))
  await expect.poll(() => strip.evaluate(el => el.scrollLeft)).toBe(1200)
  await page.waitForTimeout(100)
  // The slide stayed at index 0; now step to index 20, centered at 2050 - 300.
  await page.evaluate(() => window.uiState.go(20))
  await expect.poll(() => strip.evaluate(el => Math.round(el.scrollLeft))).toBe(1750)
})

test('the task list hears keys only while it is the visible screen', async t => {
  const page = await fixture(t, 'flow')
  await page.waitForTimeout(300)
  // With no task focused, ArrowDown moves into the list and claims the key.
  const claimed = (key, init = {}) => page.evaluate(([key, init]) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
    document.body.dispatchEvent(event)
    return event.defaultPrevented
  }, [key, init])
  assert.equal(await claimed('ArrowDown'), true)
  assert.equal(await claimed('ArrowDown', { ctrlKey: true }), false)
  assert.equal(await claimed('ArrowDown', { metaKey: true }), false)
  // An open menu or dialog keeps its keys.
  await page.evaluate(() => { const layer = document.createElement('div'); layer.dataset.escapeLayer = ''; layer.textContent = 'Menu'; layer.id = 'test-layer'; document.body.append(layer) })
  assert.equal(await claimed('ArrowDown'), false)
  await page.evaluate(() => document.getElementById('test-layer').remove())
  // Cached in the background, it leaves the keys of other screens alone.
  await page.evaluate(() => window.uiState.hide())
  await page.waitForTimeout(50)
  assert.equal(await claimed('ArrowDown'), false)
  assert.equal(await claimed('Enter'), false)
  await page.evaluate(() => window.uiState.show())
  await page.waitForTimeout(50)
  assert.equal(await claimed('ArrowDown'), true)
})
