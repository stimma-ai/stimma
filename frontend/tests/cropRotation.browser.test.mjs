import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'

const built = await build({ configFile: false, plugins: [vue()], logLevel: 'error',
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: { write: false, lib: { entry: fileURLToPath(new URL('./fixtures/cropRotation.ts', import.meta.url)), formats: ['iife'], name: 'CropTest' } },
})
const code = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code

test('rotated crop preview, pointer gestures and output retain source proportions', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  await page.setContent('<div id="app" style="position:relative;width:500px;height:500px"></div>')
  await page.addScriptTag({ content: code })
  // The 240×120 image becomes a 120×240 frame, with no pixel stretching.
  const rendered = await page.evaluate(() => {
    const { source, applyCrop } = window.cropTest
    return [0, 1, 2, 3].map(rotation90 => {
      const output = applyCrop(source, 240, 120, { rect: { x: 0.5, y: 0.5, width: 1, height: 1 }, rotation90 })
      const ctx = output.getContext('2d')
      return { size: [output.width, output.height], corners: [[10, 10], [output.width - 10, 10], [output.width - 10, output.height - 10], [10, output.height - 10]].map(([x,y]) => [...ctx.getImageData(x,y,1,1).data]) }
    })
  })
  const red = [255,0,0,255], green = [0,255,0,255], blue = [0,0,255,255], yellow = [255,255,0,255]
  assert.deepEqual(rendered, [
    { size: [240,120], corners: [red,green,yellow,blue] },
    { size: [120,240], corners: [blue,red,green,yellow] },
    { size: [240,120], corners: [yellow,blue,red,green] },
    { size: [120,240], corners: [green,yellow,blue,red] },
  ])
  const cropped = await page.evaluate(() => {
    const { source, applyCrop } = window.cropTest
    const output = applyCrop(source, 240, 120, { rect: { x: 0.25, y: 0.25, width: 0.5, height: 0.5 }, rotation90: 1 })
    return { size: [output.width, output.height], pixel: [...output.getContext('2d').getImageData(30,60,1,1).data] }
  })
  assert.deepEqual(cropped, { size: [60,120], pixel: red })
  const bounds = await page.locator('canvas').boundingBox()
  const center = { x: bounds.x + 250, y: bounds.y + 250 }
  await page.mouse.move(center.x, center.y)
  await page.mouse.down()
  await page.mouse.move(center.x + 20, center.y + 10)
  await page.mouse.up()
  const dragged = await page.evaluate(() => ({ ...window.cropTest.state.crop, commits: window.cropTest.state.commits }))
  assert.ok(Math.abs(dragged.x - (0.5 - 10/240)) < 1e-8)
  assert.ok(Math.abs(dragged.y - (0.5 + 20/120)) < 1e-8)
  assert.equal(dragged.commits, 1)
  // Grab the visible bottom-right of the portrait frame and resize it.
  await page.mouse.move(center.x + 60, center.y + 120)
  await page.mouse.down()
  await page.mouse.move(center.x + 80, center.y + 150)
  await page.mouse.up()
  const resized = await page.evaluate(() => ({ ...window.cropTest.state.crop, commits: window.cropTest.state.commits }))
  assert.ok(Math.abs(resized.width - (1 + 30/240)) < 1e-8)
  assert.ok(Math.abs(resized.height - (1 + 20/120)) < 1e-8)
  assert.equal(resized.commits, 2)
  for (const quarter of [0, 1, 2, 3]) {
    for (const flipX of [false, true]) {
      for (const tilt of [0, 0.2]) {
        await page.evaluate(({ quarter, flipX, tilt }) => {
          Object.assign(window.cropTest.state, { rotation90: quarter, flipX,
            crop: { x: 0.5, y: 0.5, width: 1, height: 1, aspectRatio: null, rotation: tilt } })
        }, { quarter, flipX, tilt })
        await page.mouse.move(center.x, center.y)
        await page.mouse.down()
        await page.mouse.move(center.x + 20, center.y + 10)
        await page.mouse.up()
        const actual = await page.evaluate(() => ({ ...window.cropTest.state.crop }))
        const q = quarter * Math.PI / 2
        const x = (Math.cos(q) * 20 + Math.sin(q) * 10) * (flipX ? -1 : 1)
        const y = -Math.sin(q) * 20 + Math.cos(q) * 10
        assert.ok(Math.abs(actual.x - (0.5 - (Math.cos(tilt)*x - Math.sin(tilt)*y)/240)) < 1e-8)
        assert.ok(Math.abs(actual.y - (0.5 - (Math.sin(tilt)*x + Math.cos(tilt)*y)/120)) < 1e-8)
      }
    }
  }

})
