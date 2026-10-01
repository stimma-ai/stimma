import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'
const built = await build({ configFile: false, plugins: [vue()], logLevel: 'error',
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/maskInspection.ts', import.meta.url)), formats: ['iife'], name: 'MaskTest' } },
})
const code = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code

test('mask inspection shows alpha coverage independent of RGB and preserves the mask', async t => {
  const browser = await chromium.launch({ headless: true })
  t.after(() => browser.close())
  const page = await browser.newPage({ deviceScaleFactor: 1 })
  await page.setContent('<div id="app"></div>')
  await page.addScriptTag({ content: code })
  const read = () => page.evaluate(() => {
    const ctx = document.querySelector('canvas').getContext('2d')
    return [20, 60, 100].map(x => [...ctx.getImageData(x, 30, 1, 1).data])
  })
  assert.deepEqual(await read(), [[255,255,255,255], [128,128,128,255], [0,0,0,255]])
  await page.evaluate(async () => { window.maskTest.state.preview = false; await window.maskTest.nextTick() })
  assert.deepEqual(await read(), [[0,0,0,0], [0,0,0,0], [0,0,0,0]])
  const alpha = await page.evaluate(() => {
    const ctx = window.maskTest.model.getSelectionMask().getContext('2d')
    return [20,60,100].map(x => ctx.getImageData(x,30,1,1).data[3])
  })
  assert.deepEqual(alpha, [255,128,0])
  await page.evaluate(async () => { window.maskTest.state.preview = true; await window.maskTest.nextTick() })
  assert.deepEqual(await read(), [[255,255,255,255], [128,128,128,255], [0,0,0,255]])
})
