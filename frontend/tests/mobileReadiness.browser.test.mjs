import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'

const buildResult = await build({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), logLevel: 'silent', plugins: [vue()],
  define: { 'process.env.NODE_ENV': '"production"' },
  css: { postcss: { plugins: [] } },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/mobileReadiness.ts', import.meta.url)), formats: ['iife'], name: 'ReadinessTest',
  } },
})
const script = (Array.isArray(buildResult) ? buildResult : [buildResult]).flatMap(result => result.output).find(item => item.type === 'chunk').code

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  page.setDefaultTimeout(10000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setContent('<style>.test-tile{width:100px;height:100px;position:relative;overflow:hidden}.test-tile img{width:100%;height:100%}.test-tile svg{width:32px;height:32px}</style><div id="app"></div>')
  await page.evaluate(phoneKind => {
    window.nativeCalls = []
    // Scripted test calls are not a physical user's Play gesture.
    Object.defineProperty(navigator, 'userActivation', { configurable: true, value: { isActive: false } })
    if (phoneKind === 'ios') window.webkit = { messageHandlers: { stimma: { postMessage: async message => { window.nativeCalls.push(message) } } } }
    else window.stimmaAndroid = { postMessage: value => {
      const message = JSON.parse(value)
      window.nativeCalls.push(message)
      queueMicrotask(() => window.stimmaAndroid.onmessage({ data: JSON.stringify({ id: message.id, result: null }) }))
    } }
  }, process.env.STIMMA_TEST_MOBILE_PLATFORM ?? 'ios')
  await page.addScriptTag({ content: script })
  assert.deepEqual(errors, [], 'fixture should load without script errors')
  return page
}

test('failed images retry on recovery, loaded images stay put, offscreen errors wait for visibility', async t => {
  const page = await fixture(t)
  let recovered = false
  const requests = []
  const png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 1; canvas.height = 1
    return canvas.toDataURL('image/png').split(',')[1]
  }), 'base64')
  await page.route('https://media.test/**', route => {
    requests.push(route.request().url())
    if (!recovered && !route.request().url().includes('steady')) return route.abort('failed')
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await page.evaluate(() => window.readiness.mountImages())
  await page.waitForFunction(() => document.querySelector('#steady img')?.naturalWidth > 0 && document.querySelector('#failed svg') && document.querySelector('#offscreen svg')).catch(async error => {
    throw new Error(`${error.message}; requests=${requests.join(',')}; markup=${await page.locator('#app').innerHTML()}`)
  })
  recovered = true
  await page.evaluate(() => window.dispatchEvent(new Event('stimma:media-reconnected')))
  await page.waitForFunction(() => document.querySelector('#failed img')?.naturalWidth > 0)
  assert.equal(requests.filter(url => url.includes('steady')).length, 1)
  assert.equal(requests.filter(url => url.includes('offscreen')).length, 1)
  await page.locator('#offscreen').scrollIntoViewIfNeeded()
  await page.waitForFunction(() => document.querySelector('#offscreen img')?.naturalWidth > 0)
  assert.equal(requests.filter(url => url.includes('offscreen')).length, 2)
  await page.evaluate(() => window.dispatchEvent(new Event('stimma:media-reconnected')))
  assert.equal(requests.filter(url => url.includes('failed')).length, 2)
})

test('background pauses actual media and refuses delayed playback until explicit Play', async t => {
  const page = await fixture(t)
  // Six seconds of silent PCM: exercises a real HTML audio pipeline.
  const wav = Buffer.alloc(44 + 8000 * 2 * 6)
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34)
  wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40)
  await page.evaluate(async src => {
    const audio = document.createElement('audio'); audio.id = 'audio'; audio.src = src
    document.body.append(audio); await audio.play()
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: false }))
  }, `data:audio/wav;base64,${wav.toString('base64')}`)
  assert.equal(await page.$eval('#audio', el => el.paused), true)
  await page.evaluate(async () => {
    window.dispatchEvent(new CustomEvent('stimma:app-active', { detail: true }))
    await document.querySelector('#audio').play().catch(() => {})
  })
  await page.waitForFunction(() => document.querySelector('#audio').paused)
  await page.evaluate(async () => { window.readiness.allowMobilePlayback(); await document.querySelector('#audio').play() })
  assert.equal(await page.$eval('#audio', el => el.paused), false)
})

test('cached slideshow wake leases cannot release the active slideshow assertion', async t => {
  const page = await fixture(t)
  await page.evaluate(async () => {
    const first = window.readiness.createMobileKeepAwakeLease(), second = window.readiness.createMobileKeepAwakeLease()
    await first(true); await second(true); await first(false); await second(false)
  })
  assert.deepEqual(await page.evaluate(() => window.nativeCalls.map(call => call.args.active)), [true, true, true, false])
})
