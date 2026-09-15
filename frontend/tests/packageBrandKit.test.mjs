import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from '@playwright/test'

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), 'stimma-brand-components-'))
  execFileSync('uv', ['run', 'python', '-c', `
from pathlib import Path
from packages.cover import render_cover_document
from packages.export import export_single_html
from packages.manifest import new_manifest, write_manifest
out = Path(${JSON.stringify(dir)})
font = Path('packages/mockups/assets/fonts/NotoSans-Regular.ttf')
(out / 'font.ttf').write_bytes(font.read_bytes())
m = new_manifest(title='Identity exploration')
m['members'] = [{'id':'font','name':'font.ttf','path':'font.ttf'}]
body = '''<div class="sp-page"><h1 class="sp-title">Identity exploration</h1>
<p class="sp-note">Candidate · not approved</p>
<stimma-grid>
<stimma-swatch value="#E87733" label="Apricot" usage="Decorative accent"></stimma-swatch>
<stimma-swatch value="#172334" label="Ink" usage="Text on Paper"></stimma-swatch>
<stimma-swatch value="#F5F7FA" label="Paper" usage="Application background"></stimma-swatch>
</stimma-grid><stimma-section label="Typography">
<stimma-type ref="font" label="Body · Noto Sans Regular">Make something together.</stimma-type>
</stimma-section></div>'''
html, errors = render_cover_document(m, authored_html=body, bundle_dir=out)
assert not errors, errors
(out / 'index.html').write_text(html)
write_manifest(out, m)
(out / 'offline.html').write_text(export_single_html(out))
`], { cwd: new URL('../../backend', import.meta.url).pathname, stdio: ['ignore', 'ignore', 'inherit'] })
  return pathToFileURL(join(dir, 'offline.html')).href
}

test('brand components remain readable offline, without scripts, at phone and desktop widths', async () => {
  const url = fixture()
  const browser = await chromium.launch({ headless: true })
  try {
    for (const width of [390, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false })
      const requests = []
      page.on('request', r => requests.push(r.url()))
      await page.goto(url)
      await page.evaluate(() => document.fonts.ready)
      const facts = await page.evaluate(() => {
        const sample = document.querySelector('.sp-type-sample')
        const swatch = document.querySelector('.sp-swatch-color')
        const label = document.querySelector('.sp-swatch-label')
        return {
          overflow: document.documentElement.scrollWidth > innerWidth,
          background: getComputedStyle(document.body).backgroundColor,
          color: getComputedStyle(swatch).backgroundColor,
          labelBelow: label.getBoundingClientRect().top >= swatch.getBoundingClientRect().bottom,
          loadedFont: [...document.fonts].some(f => f.family.startsWith('spfont') && f.status === 'loaded'),
          fontFamily: getComputedStyle(sample).fontFamily,
          footerCount: document.querySelectorAll('.sp-footer').length,
        }
      })
      assert.equal(facts.overflow, false)
      assert.equal(facts.background, 'rgb(13, 13, 14)')
      assert.equal(facts.color, 'rgb(232, 119, 51)')
      assert.equal(facts.labelBelow, true)
      assert.equal(facts.loadedFont, true)
      assert.match(facts.fontFamily, /spfont/)
      assert.equal(facts.footerCount, 1)
      assert.equal(requests.some(r => /^https?:/.test(r)), false)
      await page.close()
    }
  } finally {
    await browser.close()
  }
})
