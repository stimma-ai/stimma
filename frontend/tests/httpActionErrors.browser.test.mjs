import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, __STIMMA_DISTRIBUTION__: '"official"', 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/httpActionErrors.ts', import.meta.url)), name: 'HttpActionErrorsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t, status) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('**/*', route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' })
    if (request.method() === 'PATCH') return route.fulfill({ status, json: { detail: 'Save refused' } })
    if (path === '/api/chats/previews') return route.fulfill({ json: { items: [{ id: 1, name: 'Saved chat name' }] } })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://http-action-errors.test/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect(page.getByText('Saved chat name', { exact: true })).toBeVisible()
  return page
}

for (const status of [400, 500]) {
  test(`HTTP ${status} chat rename keeps the saved name and shows one toast`, async t => {
    const page = await fixture(t, status)
    await page.getByText('Saved chat name', { exact: true }).click()
    const input = page.getByPlaceholder('Name this chat...')
    await input.fill('Unsaved chat name')
    await input.press('Enter')
    await expect(input).toHaveCount(0)
    await expect(page.getByText('Saved chat name', { exact: true })).toBeVisible()
    await expect(page.getByText('Unsaved chat name', { exact: true })).toHaveCount(0)
    await expect(page.getByText("Couldn't rename chat.", { exact: true })).toHaveCount(1)
  })

  test(`HTTP ${status} telemetry update rolls back without emitting and shows one toast`, async t => {
    const page = await fixture(t, status)
    const toggle = page.locator('button[aria-pressed]')
    await expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await toggle.click()
    await expect(page.getByText("Couldn't save privacy setting.", { exact: true })).toHaveCount(1)
    await expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await expect(toggle).toBeEnabled()
    assert.deepEqual(await page.evaluate(() => window.httpActionErrors.telemetryUpdates), [])
  })
}

test('successful HTTP saves update the chat name and emit telemetry changes', async t => {
  const page = await fixture(t, 200)
  await page.getByText('Saved chat name', { exact: true }).click()
  const input = page.getByPlaceholder('Name this chat...')
  await input.fill('Updated chat name')
  await input.press('Enter')
  await expect(page.getByText('Updated chat name', { exact: true })).toBeVisible()
  const toggle = page.locator('button[aria-pressed]')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => page.evaluate(() => window.httpActionErrors.telemetryUpdates)).toEqual([true])
  await expect(page.getByText(/Couldn't/)).toHaveCount(0)
})
