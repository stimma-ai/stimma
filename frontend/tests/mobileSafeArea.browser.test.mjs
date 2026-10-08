import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium } from '@playwright/test'

const built = await build({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), logLevel: 'error',
  build: { write: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/mobileSafeArea.ts', import.meta.url)), formats: ['iife'], name: 'SafeAreaTest',
  } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
// Desktop Chromium has no cutout. Simulate nonzero environment insets in the
// generated CSS while leaving the production shell override intact.
const css = output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))
  .map(item => String(item.source).replace(/env\(safe-area-inset-(top|bottom|left|right)(?:\s*,[^)]*)?\)/g, '40px')).join('\n')
const script = output.find(item => item.type === 'chunk').code

for (const platform of ['android', 'ios', 'browser']) {
  for (const width of [360, 752]) test(`${platform} safe areas at ${width}px`, async t => {
    const browser = await chromium.launch()
    t.after(() => browser.close())
    const page = await browser.newPage({ viewport: { width, height: 844 } })
    await page.setContent('<div id="app"><header class="pt-safe"><div style="height:60px">Assets</div></header><main>Browser content</main><section id="slideshow" class="pt-safe pb-safe pl-safe pr-safe">Slideshow</section></div>')
    await page.evaluate(platform => {
      if (platform === 'android') window.stimmaAndroid = { postMessage() {} }
      if (platform === 'ios') window.webkit = { messageHandlers: { stimma: { postMessage() {} } } }
    }, platform)
    await page.addStyleTag({ content: css })
    await page.addScriptTag({ content: script })
    const geometry = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement)
      const slideshow = getComputedStyle(document.querySelector('#slideshow'))
      return {
        platform: document.documentElement.dataset.mobilePlatform,
        safe: ['top', 'bottom', 'left', 'right'].map(edge => root.getPropertyValue(`--safe-${edge}`).trim()),
        contentTop: document.querySelector('main').getBoundingClientRect().top,
        slideshowPadding: [slideshow.paddingTop, slideshow.paddingBottom, slideshow.paddingLeft, slideshow.paddingRight],
      }
    })
    const inset = platform === 'android' ? '0px' : '40px'
    assert.equal(geometry.platform, platform === 'browser' ? undefined : platform)
    assert.deepEqual(geometry.safe, Array(4).fill(inset))
    assert.equal(geometry.contentTop, platform === 'android' ? 60 : 100)
    assert.deepEqual(geometry.slideshowPadding, Array(4).fill(inset))
  })
}
