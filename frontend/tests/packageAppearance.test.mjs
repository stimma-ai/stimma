import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from '@playwright/test'

// <stimma-appearance> is a kit component an authored cover places around
// anything that comes in a light and a dark rendering. One appearance shows
// at a time, chosen by the reader, defaulting to the system. It is pure CSS,
// so it must behave identically with scripts off.

function renderAuthoredCover(t) {
  const dir = mkdtempSync(join(tmpdir(), 'stimma-appearance-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  const script = `
from pathlib import Path
from PIL import Image
from packages.manifest import new_manifest, write_manifest, sha256_file
from packages.cover import render_cover_document

out = Path(${JSON.stringify('%DIR%')})
previews = out / 'app-icons' / 'previews'
previews.mkdir(parents=True)
# Appearance switching only needs real image files; a marketplace recipe must
# not make this cover-component regression depend on a developer's profile.
for surface in ('home', 'settings'):
    for appearance, color in (('light', '#F5F5F5'), ('dark', '#151515')):
        Image.new('RGB', (360, 720), color).save(previews / f'{surface}-{appearance}.png')
m = new_manifest(title='Dot')
m['runs'] = [{'id': 'r1', 'recipe': {'id': 'fixture', 'version': 1, 'display_name': 'Appearance previews'},
              'inputs': {}, 'params': {}, 'root': 'app-icons/',
              'files': [{'path': 'app-icons/' + str(p.relative_to(out / 'app-icons')),
                         'hash': sha256_file(p), 'size': p.stat().st_size}
                        for p in sorted(previews.glob('*.png'))]}]
cover = '''<div class="sp-page"><h1 class="sp-title">Dot</h1>
<stimma-section><stimma-appearance label="On a home screen">
  <div when="light"><stimma-media ref="app-icons/previews/home-light.png" style="width:360px"></stimma-media></div>
  <div when="dark"><stimma-media ref="app-icons/previews/home-dark.png" style="width:360px"></stimma-media></div>
</stimma-appearance></stimma-section>
<stimma-section label="Everywhere else"><stimma-appearance>
  <div when="light" style="display:grid"><stimma-media ref="app-icons/previews/settings-light.png"></stimma-media></div>
  <p when="light" class="extra-light">Additional details</p>
  <div when="dark"><stimma-media ref="app-icons/previews/settings-dark.png"></stimma-media></div>
</stimma-appearance></stimma-section>
<stimma-files ref="r1"></stimma-files></div>'''
html, problems = render_cover_document(m, authored_html=cover, bundle_dir=out)
assert not problems, problems
(out / 'index.html').write_text(html)
write_manifest(out, m)
`.replace('%DIR%', dir)
  execFileSync('uv', ['run', 'python', '-c', script], {
    cwd: new URL('../../backend', import.meta.url).pathname,
    stdio: ['ignore', 'ignore', 'inherit'],
  })
  return pathToFileURL(join(dir, 'index.html')).href
}

const visible = (page, sel) => page.evaluate(s =>
  Array.from(document.querySelectorAll(s)).filter(el => el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden').length, sel)

for (const javaScriptEnabled of [true, false]) {
  test(`one appearance at a time, chosen by the reader (scripts ${javaScriptEnabled ? 'on' : 'off'})`, async t => {
    const url = renderAuthoredCover(t)
    const browser = await chromium.launch({ headless: true })
    try {
      for (const scheme of ['light', 'dark']) {
        const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, javaScriptEnabled, colorScheme: scheme })
        const errors = []
        page.on('pageerror', e => errors.push(e.message))
        await page.goto(url)
        await page.locator("img").evaluateAll(images => Promise.all(images.map(img => { img.loading = "eager"; return img.decode() })))

        // Two switches on the page, each its own radio group.
        assert.equal(await page.locator('stimma-appearance .sp-seg').count(), 2)
        assert.equal(await page.locator('stimma-appearance .sp-label').textContent(), 'On a home screen')

        // Default follows the system.
        const light = await visible(page, '[when="light"] stimma-media')
        const dark = await visible(page, '[when="dark"] stimma-media')
        if (scheme === 'light') { assert.ok(light > 0); assert.equal(dark, 0) }
        else { assert.ok(dark > 0); assert.equal(light, 0) }

        // The reader overrides the system, per switch.
        const first = page.locator('stimma-appearance').first()
        const beforeHeight = await first.evaluate(el => el.getBoundingClientRect().height)
        await first.locator('label.sp-dark').click()
        if (scheme === 'light') {
          const during = await first.evaluate(el => {
            const animations = el.getAnimations({ subtree: true })
            for (const animation of animations) { animation.pause(); animation.currentTime = 90 }
            const opacity = Array.from(el.querySelectorAll('.sp-appearance-panel')).map(p => Number(getComputedStyle(p).opacity))
            for (const animation of animations) animation.finish()
            return opacity
          })
          assert.ok(during.every(value => value > 0 && value < 1), `expected a crossfade, got ${during}`)
        }
        await page.waitForTimeout(250)
        assert.equal(await first.evaluate(el => el.getBoundingClientRect().height), beforeHeight)
        assert.equal(await visible(page, '#stimma-appearance-1 [when="light"] stimma-media'), 0)
        assert.ok(await visible(page, '#stimma-appearance-1 [when="dark"] stimma-media') > 0)
        await first.locator('label.sp-light').click()
        await page.waitForTimeout(250)
        assert.equal(await visible(page, '#stimma-appearance-1 [when="dark"] stimma-media'), 0)
        assert.ok(await visible(page, '#stimma-appearance-1 [when="light"] stimma-media') > 0)

        // Never both: no light and dark of the same thing visible together.
        assert.equal(await visible(page, '[when="light"] stimma-media, [when="dark"] stimma-media'), 2)
        const second = page.locator('stimma-appearance').nth(1)
        await second.locator('label.sp-light').click()
        await page.waitForTimeout(250)
        assert.equal(await second.locator('div[when="light"]').evaluate(el => getComputedStyle(el).display), 'grid')
        const positions = await second.evaluate(el => ({
          imageBottom: el.querySelector('div[when="light"]').getBoundingClientRect().bottom,
          textTop: el.querySelector('.extra-light').getBoundingClientRect().top,
        }))
        assert.ok(positions.textTop >= positions.imageBottom)
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await first.locator('label.sp-dark').click()
        assert.equal(await first.locator('.sp-appearance-panel').first().evaluate(el => getComputedStyle(el).transitionDuration), '0s')
        assert.equal(await visible(page, '#stimma-appearance-1 [when="light"] stimma-media'), 0)
        assert.deepEqual(errors, [])
        await page.close()
      }
    } finally {
      await browser.close()
    }
  })
}
