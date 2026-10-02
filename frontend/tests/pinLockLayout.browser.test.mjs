import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwind from 'tailwindcss'
import loadConfig from 'tailwindcss/loadConfig.js'
import { chromium } from '@playwright/test'

const root = fileURLToPath(new URL('..', import.meta.url))
const app = readFileSync(`${root}/src/App.vue`, 'utf8')
// Render the actual lock template with isolated state, without a profile DB.
const template = app.slice(app.indexOf('  <!-- Full-screen lock screen'), app.indexOf('  <!-- No-chrome mode'))
  .replace('v-else-if="isLocked"', 'v-if="isLocked"')
const entryId = `${root}/tests/fixtures/pinLockLayout.js`
const fixtureId = `${root}/tests/fixtures/pinLockLayout.vue`
const config = loadConfig(`${root}/tailwind.config.js`)
const result = await build({
  configFile: false, root, logLevel: 'silent',
  plugins: [{
    name: 'pin-lock-fixture', enforce: 'pre',
    resolveId(id) { if (id.endsWith('pinLockLayout.js')) return entryId; if (id.endsWith('pinLockLayout.vue')) return fixtureId },
    load(id) {
      if (id === entryId) return `import { createApp } from 'vue'; import App from ${JSON.stringify(fixtureId)}; import ${JSON.stringify(`${root}/src/style.css`)}; createApp(App).mount('#app')`
      if (id === fixtureId) return `<template>${template}</template><script setup>
        import { ref, computed } from 'vue'
        import FitToSpace from '../../src/components/FitToSpace.vue'
        const isLocked = true, isCompact = true, lockedProfileName = 'Test profile'
        const profiles = [], lockGlowBlobs = [], currentProfileId = 'test'
        const lockScreenPinInput = ref(null), lockScreenProfileDropdownOpen = ref(false)
        const lockScreenPin = ref(''), lockScreenError = ref(''), lockScreenSubmitting = ref(false), lockScreenShake = ref(false)
        const lockScreenDotCount = computed(() => Math.max(4, lockScreenPin.value.length))
        function lockScreenKey(k) { lockScreenPin.value = k === 'del' ? lockScreenPin.value.slice(0, -1) : (lockScreenPin.value + k).slice(0, 20); lockScreenPinInput.value.focus() }
        function submitLockScreenPin() { lockScreenError.value = 'Invalid PIN. Please try again.'; lockScreenPin.value = '' }
        function toggleLockScreenProfileDropdown() { lockScreenProfileDropdownOpen.value = !lockScreenProfileDropdownOpen.value }
        function switchToProfileFromLockScreen() {}
        const GlowCanvas = { template: '<div />' }, Spinner = { template: '<span />' }
      </script>`
    },
  }, vue()],
  define: { 'process.env.NODE_ENV': '"production"' },
  css: { postcss: { plugins: [tailwind({ ...config, content: [`${root}/src/**/*.{vue,js,ts}`] })] } },
  build: { write: false, lib: { entry: entryId, formats: ['iife'], name: 'PinLockTest' } },
})
const output = (Array.isArray(result) ? result : [result]).flatMap(r => r.output)
const script = output.find(item => item.type === 'chunk').code
const css = output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n')

test('PIN panel scales on live resize; every key and error stays inside the safe area', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/logo.svg' || /^\/fonts\/GeneralSans-[A-Za-z]+\.woff2$/.test(path)) return route.fulfill({ path: `${root}/public${path}` })
    return route.fulfill({ contentType: 'text/html', body: '<html data-theme="dark"><body><div id="app"></div></body></html>' })
  })
  await page.goto('http://pin-lock.test/')
  await page.addStyleTag({ content: css.replace(/@import[^;]+;/g, '') })
  await page.addScriptTag({ content: script })
  await page.evaluate(() => document.fonts.ready)
  for (const [width, height, safeTop, safeBottom] of [
    [1440, 900, 0, 0], [960, 520, 0, 0], [800, 400, 0, 0],
    [390, 844, 59, 34], [844, 390, 0, 21], [320, 320, 0, 0], [1440, 900, 0, 0],
  ]) {
    await page.setViewportSize({ width, height })
    await page.evaluate(([top, bottom]) => {
      document.documentElement.style.setProperty('--safe-top', `${top}px`)
      document.documentElement.style.setProperty('--safe-bottom', `${bottom}px`)
    }, [safeTop, safeBottom])
    await page.waitForFunction(({ safeTop, safeBottom }) => [...document.querySelectorAll('.lock-key')].every(el => {
      const r = el.getBoundingClientRect()
      return r.top >= safeTop + 64 - 1 && r.bottom <= innerHeight - safeBottom - 24 + 1
    }), { safeTop, safeBottom })
    const bounds = await page.locator('.lock-key, h1, img').evaluateAll(elements => elements.map(el => {
      const r = el.getBoundingClientRect()
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom }
    }))
    for (const r of bounds) {
      assert.ok(r.x >= 23 && r.right <= width - 23 && r.y >= safeTop + 63 && r.bottom <= height - safeBottom - 23, JSON.stringify({ width, height, r }))
    }
    await page.getByRole('button', { name: '1', exact: true }).click()
    await page.getByRole('button', { name: '0', exact: true }).click()
    assert.equal(await page.getByLabel('PIN', { exact: true }).inputValue(), '10')
    await page.getByTitle('Delete', { exact: true }).click()
    assert.equal(await page.getByLabel('PIN', { exact: true }).inputValue(), '1')
    await page.getByTitle('Unlock', { exact: true }).click()
    const error = await page.getByText('Invalid PIN. Please try again.', { exact: true }).boundingBox()
    assert.ok(error.y >= safeTop + 64 && error.y + error.height <= height - safeBottom - 24)
    const scale = await page.locator('[style*="scale("]').evaluate(el => Number(el.style.transform.match(/scale\(([^)]+)/)[1]))
    assert.equal(scale === 1, height >= 800, `${width}×${height}: scale=${scale}`)
  }
  assert.deepEqual(errors, [])
})
