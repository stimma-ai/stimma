import assert from 'node:assert/strict'
import test from 'node:test'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'

test('disabled analysis backlog stays idle and enabling a phase updates the panel', async () => {
  const built = await build({
    configFile: false,
    plugins: [vue()],
    logLevel: 'error',
    define: { 'process.env.NODE_ENV': JSON.stringify('production'), __STIMMA_DISTRIBUTION__: JSON.stringify('dev'), __STIMMA_COMMIT__: JSON.stringify('test') },
    build: {
      write: false, minify: false,
      lib: { entry: 'tests/fixtures/backgroundWork.js', name: 'BackgroundWorkTest', formats: ['iife'] },
    },
  })
  const bundle = (Array.isArray(built) ? built[0] : built).output.find(item => item.type === 'chunk').code
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('http://localhost/**', route => route.fulfill(
      new URL(route.request().url()).pathname === '/'
        ? { contentType: 'text/html', body: '<div id="app"></div>' }
        : { json: {} },
    ))
    await page.goto('http://localhost/')
    await page.addScriptTag({ content: bundle })
    await page.evaluate(() => {
      const phase = (enabled, pending, completed, failed = 0) => ({ enabled, pending, completed, failed, processing: 0 })
      window.backgroundWork.stats.value = {
        metadata: phase(true, 0, 4266),
        clip: phase(false, 83, 4150),
        face_detection: phase(false, 874, 3359),
        vlm_caption: phase(false, 4233, 0, 2),
      }
    })
    assert.equal(await page.getByTestId('indicator').count(), 0)
    assert.equal(await page.getByText('Visual Indexing', { exact: true }).count(), 0)
    assert.equal(await page.getByText('Face Analysis', { exact: true }).count(), 0)
    assert.equal(await page.getByText('Visual Analysis', { exact: true }).count(), 0)
    await page.evaluate(() => { window.backgroundWork.stats.value.clip.enabled = true })
    try {
      await page.getByText('Visual Indexing', { exact: true }).waitFor({ timeout: 5000 })
    } catch (error) {
      assert.fail(`${error.message}; errors: ${errors.join('; ')}; body: ${await page.locator('body').innerText()}`)
    }
    assert.equal(await page.getByTestId('indicator').count(), 1)
    assert.equal(await page.evaluate(() => window.backgroundWork.totalPending.value), 83)
    await page.evaluate(() => { window.backgroundWork.stats.value.clip.enabled = false })
    await page.getByTestId('indicator').waitFor({ state: 'detached' })
    // Metadata remains visible and active independently of AI settings.
    await page.evaluate(() => { window.backgroundWork.stats.value.metadata.pending = 1 })
    await page.getByTestId('indicator').waitFor({ state: 'attached' })
    assert.equal(await page.evaluate(() => window.backgroundWork.totalPending.value), 1)
    assert.deepEqual(errors, [])
  } finally {
    await browser.close()
  }
})
