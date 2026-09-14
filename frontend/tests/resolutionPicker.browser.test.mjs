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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/resolutionPicker.ts', import.meta.url)), name: 'ResolutionTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

test('local 4 MP, custom dimensions, and cloud aspect limits in the rendered picker', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  await page.setContent('<div id="app"></div>')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.locator('#app button').click()
  const slider = page.getByRole('slider', { name: 'Output size' })
  await expect(slider).toHaveAttribute('max', '2')
  await page.getByRole('button', { name: '21:9', exact: true }).click()
  await expect(slider).toHaveAttribute('max', '2')
  const dimensions = page.getByRole('spinbutton')
  assert.deepEqual(await dimensions.evaluateAll(els => els.map(el => Number(el.value))), [3136, 1344])

  await dimensions.nth(0).fill('4096')
  await dimensions.nth(0).press('Tab')
  await expect(dimensions.nth(0)).toHaveValue('4096')
  await expect(dimensions.nth(1)).toHaveValue('1344')
  await expect(page.getByText(/Custom size ·/)).toBeVisible()
  await expect(slider).toHaveAttribute('max', '2')
  await page.keyboard.press('Escape')
  await page.locator('#app button').click()
  await expect(dimensions.nth(0)).toHaveValue('4096')
  await slider.focus()
  await slider.press('Home')
  await expect(page.getByText(/Custom size ·/)).toHaveCount(0)

  await page.evaluate(() => {
    const s = window.resolutionTest
    s.schema = { width: { minimum: 128, maximum: 2048, 'x-step': 16 }, height: { minimum: 128, maximum: 2048, 'x-step': 16 } }
    s.policy = { ...s.policy, ratio: '21:9', mp: 4 }
  })
  await expect(dimensions.nth(0)).toHaveValue('2048')
  await expect(dimensions.nth(1)).toHaveValue('880')
  assert.ok(Math.abs(Number(await slider.getAttribute('max')) - Math.log2(12 / 7)) < 0.001)
  await expect(page.getByText(/Size reduced to/)).toBeVisible()
  await page.getByRole('button', { name: '1:1', exact: true }).click()
  await expect(slider).toHaveAttribute('max', '2')
  await expect(dimensions.nth(1)).toHaveValue('2048')
})
