import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium } from '@playwright/test'
import config from '../vite.config.js'

// The agent's CSS and markup must style the sheet and nothing else, and must
// never make the browser fetch anything.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/contactSheetHtml.ts', import.meta.url)), name: 'ContactSheetHtmlTest', formats: ['iife'] } },
})
const script = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(file => file.type === 'chunk').code

test('agent CSS stays inside the sheet and loads nothing', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const external = []
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.hostname === 'app.test') return route.fulfill({ contentType: 'text/html', body: '<html><body><main id="app">App</main></body></html>' })
    external.push(url.href)
    return route.fulfill({ status: 204 })
  })
  await page.goto('http://app.test/')
  await page.addScriptTag({ content: script })
  const result = await page.evaluate(() => {
    const { parseSheet } = window.SheetHtml
    const scope = '[data-sheet-scope="s1"]'
    const html = `<style>
      body:has(&) { display: none }
      :root { --cs-fg: red }
      .tile { color: rgb(1, 2, 3); background-image: u\\72l(https://evil.example/sheet-pixel) }
      .card, body:has(.tile) { outline: 3px solid red }
      .outer { .inner { color: red } }
      @font-face { font-family: x; src: url(https://evil.example/font) }
      @media (min-width: 1px) { .tile { padding: 2px } }
    </style>
    <div class="tile">tile</div>
    <div class="card" style="background: u\\72l(https://evil.example/inline); margin: 4px">card</div>`
    const parsed = parseSheet(html, scope)
    const host = document.createElement('div')
    host.setAttribute('data-sheet-scope', 's1')
    host.append(...Array.from(parsed.root.childNodes))
    const style = document.createElement('style')
    style.textContent = parsed.css
    document.body.append(style, host)
    const tile = host.querySelector('.tile')
    const card = host.querySelector('.card')
    return {
      css: parsed.css,
      bodyDisplay: getComputedStyle(document.body).display,
      bodyOutline: getComputedStyle(document.body).outlineStyle,
      tileColor: getComputedStyle(tile).color,
      tilePadding: getComputedStyle(tile).paddingTop,
      cardStyle: card.getAttribute('style') || '',
      cardMargin: getComputedStyle(card).marginTop,
    }
  })
  await page.waitForTimeout(300)
  assert.equal(result.bodyDisplay, 'block', 'nothing in a sheet hides the app')
  assert.equal(result.bodyOutline, 'none', 'a selector list cannot reach an ancestor')
  assert.equal(result.tileColor, 'rgb(1, 2, 3)', 'ordinary rules still style the sheet')
  assert.equal(result.tilePadding, '2px', 'media queries are kept, scoped')
  assert.equal(result.cardMargin, '4px', 'safe inline styles are kept')
  assert.ok(!/url|evil/i.test(result.css + result.cardStyle), result.css + result.cardStyle)
  assert.deepEqual(external, [], 'no external requests')
})
