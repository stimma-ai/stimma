import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwind from 'tailwindcss'
import loadConfig from 'tailwindcss/loadConfig.js'
import { chromium } from '@playwright/test'

const tailwindConfig = loadConfig(fileURLToPath(new URL('../tailwind.config.js', import.meta.url)))
const result = await build({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), logLevel: 'silent',
  plugins: [vue()], define: { 'process.env.NODE_ENV': '"production"' },
  css: { postcss: { plugins: [tailwind({ ...tailwindConfig, content: [fileURLToPath(new URL('../src/**/*.{vue,js,ts}', import.meta.url))] })] } },
  build: { write: false, lib: {
    entry: fileURLToPath(new URL('../src/mobile/main.ts', import.meta.url)), formats: ['iife'], name: 'ConnectionTest',
  } },
})
const output = (Array.isArray(result) ? result : [result]).flatMap(r => r.output)
const script = output.find(item => item.type === 'chunk').code
const css = output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n')

async function fixture(t, viewport = { width: 390, height: 844 }) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport })
  page.setDefaultTimeout(10000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/*', route => route.request().url() === 'http://connection.test/'
    ? route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }) : route.abort())
  await page.goto('http://connection.test/')
  await page.evaluate(() => {
    window.info = {
      authenticated: true, restoring: false, busy: false, liveDiscovery: true,
      discoveryState: 'live', devServerAvailable: true, user: { email: 'tester@example.com' },
      devices: Array.from({ length: 8 }, (_, i) => ({ deviceId: `server-${i}`, name: `Server ${i}`, serving: true, online: true })),
    }
    window.calls = []
    window.webkit = { messageHandlers: { stimma: { postMessage: async message => {
      window.calls.push(message)
      return message.method === 'connectionInfo' ? structuredClone(window.info) : null
    } } } }
  })
  await page.addStyleTag({ content: css.replace(/@import[^;]+;/g, '') + '\n:root{--safe-top:59px;--safe-bottom:34px;--safe-left:0px;--safe-right:0px}' })
  await page.addScriptTag({ content: script })
  await page.getByRole('button', { name: 'Connection options', exact: true }).waitFor()
  return page
}

test('native events update server presence and roster without a refresh button or polling', async t => {
  const page = await fixture(t)
  assert.equal(await page.getByRole('button', { name: 'Refresh', exact: true }).count(), 0)
  await page.evaluate(() => {
    window.info.devices[0].online = false
    window.info.devices.splice(1, 1)
    window.dispatchEvent(new Event('stimma:connection-info'))
  })
  await page.getByRole('button', { name: 'Server 0 Offline' }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Server 1 Online' }).count(), 0)
  assert.equal(await page.evaluate(() => window.calls.filter(c => c.method === 'refreshDevices').length), 0)
  await page.evaluate(() => {
    window.info.discoveryState = 'reconnecting'
    window.dispatchEvent(new Event('stimma:connection-info'))
  })
  await page.getByText('Reconnecting to server updates…').waitFor()
  assert.equal(await page.getByRole('button', { name: 'Server 2 Online' }).count(), 0)
})

test('safe area bounds the scrollport and Dev server stays reachable at phone and keyboard heights', async t => {
  const page = await fixture(t)
  await page.getByRole('button', { name: 'Connection options' }).click()
  const dev = page.getByRole('menuitem', { name: 'Dev server', exact: true })
  const box = await dev.boundingBox()
  assert.ok(box.y >= 59 && box.y + box.height <= 844 - 34)
  await dev.click()
  const input = page.getByLabel('Server IP and frontend port')
  await input.fill('192.168.1.20:9407')
  for (const viewport of [{ width: 390, height: 844 }, { width: 390, height: 420 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(viewport)
    const connect = page.getByRole('button', { name: 'Connect to dev server', exact: true })
    await connect.scrollIntoViewIfNeeded()
    const action = await connect.boundingBox()
    assert.ok(action.y >= 59 && action.y + action.height <= viewport.height - 34, JSON.stringify({ viewport, action }))
    const bounds = await page.locator('main > div').evaluate(el => {
      const rect = el.getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom, width: el.scrollWidth, clientWidth: el.clientWidth }
    })
    assert.ok(bounds.top >= 59 && bounds.bottom <= viewport.height - 34)
    assert.equal(bounds.width, bounds.clientWidth)
  }
  await page.getByRole('button', { name: 'Connect to dev server', exact: true }).click()
  assert.deepEqual(await page.evaluate(() => window.calls.find(c => c.method === 'connectDevServer').args), { address: '192.168.1.20:9407' })
})


test('options menu holds account info, Dev server, and Sign out', async t => {
  const page = await fixture(t)
  const options = page.getByRole('button', { name: 'Connection options' })
  for (const text of ['tester@example.com', 'Sign out', 'Dev server']) assert.equal(await page.getByText(text, { exact: true }).count(), 0)
  await options.click()
  const menu = page.getByRole('menu')
  await menu.getByText('tester@example.com').waitFor()
  await menu.getByRole('menuitem', { name: 'Dev server', exact: true }).waitFor()
  await page.keyboard.press('Escape')
  assert.equal(await menu.count(), 0)
  assert.equal(await options.evaluate(el => el === document.activeElement), true)
  await options.click()
  await page.locator('header').click({ position: { x: 2, y: 20 } })
  assert.equal(await menu.count(), 0)
  await options.click()
  await menu.getByRole('menuitem', { name: 'Sign out' }).click()
  assert.equal(await menu.count(), 0)
  assert.equal(await page.evaluate(() => window.calls.filter(c => c.method === 'logout').length), 1)
  assert.equal(await page.locator('footer').getByText('tester@example.com').count(), 0)
})
