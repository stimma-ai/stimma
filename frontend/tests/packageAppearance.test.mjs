import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from '@playwright/test'

// <stimma-appearance> is a kit component an authored cover places around
// anything that comes in a light and a dark rendering. One appearance shows
// at a time, chosen by the reader, defaulting to the system. It is pure CSS,
// so it must behave identically with scripts off.

function renderAuthoredCover() {
  const dir = mkdtempSync(join(tmpdir(), 'stimma-appearance-'))
  const script = `
import asyncio, sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, '.')
from packages.recipes import get_recipe, run_recipe, ResolvedInput, describe_file
from packages.manifest import new_manifest, write_manifest, sha256_file
from packages.cover import render_cover_document

out = Path(${JSON.stringify('%DIR%')})
(out / 'members').mkdir(parents=True)
img = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0))
ImageDraw.Draw(img).ellipse((80, 80, 944, 944), fill=(20, 120, 200, 255))
src = out / 'members' / 'mark.png'
img.save(src)
ri = ResolvedInput(role='master', path=src, hash=sha256_file(src), **describe_file(src))

async def main():
    r = await run_recipe(get_recipe('app-icons'), {'master': ri},
                         {'platforms': ['ios'], 'background': '#FFFFFF', 'app_name': 'Dot'},
                         out / 'app-icons', slug='dot')
    m = new_manifest(title='Dot')
    m['members'] = [{'id': 'm1', 'role': 'master', 'name': 'mark.png', 'path': 'members/mark.png',
                     'hash': ri.hash, 'size': src.stat().st_size, 'width': 1024, 'height': 1024}]
    m['runs'] = [{'id': 'r1', 'recipe': {'id': 'app-icons', 'version': 2, 'display_name': 'App icon set'},
                  'inputs': {'master': 'm1'}, 'params': r.params, 'root': 'app-icons/',
                  'files': [{'path': 'app-icons/' + f.path, 'hash': f.hash, 'size': f.size} for f in r.files]}]
    # The agent's cover: the home screen in one appearance at a time.
    cover = '''<div class="sp-page"><h1 class="sp-title">Dot</h1>
<stimma-section><stimma-appearance label="On a home screen">
  <div when="light"><stimma-media ref="app-icons/previews/home-light.png" style="width:360px"></stimma-media></div>
  <div when="dark"><stimma-media ref="app-icons/previews/home-dark.png" style="width:360px"></stimma-media></div>
</stimma-appearance></stimma-section>
<stimma-section label="Everywhere else"><stimma-appearance>
  <div when="light"><stimma-media ref="app-icons/previews/settings-light.png"></stimma-media></div>
  <div when="dark"><stimma-media ref="app-icons/previews/settings-dark.png"></stimma-media></div>
</stimma-appearance></stimma-section>
<stimma-files ref="r1"></stimma-files></div>'''
    html, problems = render_cover_document(m, authored_html=cover, bundle_dir=out)
    assert not problems, problems
    (out / 'index.html').write_text(html)
    write_manifest(out, m)
asyncio.run(main())
`.replace('%DIR%', dir)
  execFileSync('uv', ['run', 'python', '-c', script], {
    cwd: new URL('../../backend', import.meta.url).pathname,
    stdio: ['ignore', 'ignore', 'inherit'],
  })
  return pathToFileURL(join(dir, 'index.html')).href
}

const visible = (page, sel) => page.evaluate(s =>
  Array.from(document.querySelectorAll(s)).filter(el => el.offsetParent !== null).length, sel)

for (const javaScriptEnabled of [true, false]) {
  test(`one appearance at a time, chosen by the reader (scripts ${javaScriptEnabled ? 'on' : 'off'})`, async () => {
    const url = renderAuthoredCover()
    const browser = await chromium.launch({ headless: true })
    try {
      for (const scheme of ['light', 'dark']) {
        const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, javaScriptEnabled, colorScheme: scheme })
        const errors = []
        page.on('pageerror', e => errors.push(e.message))
        await page.goto(url)

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
        await first.locator('label.sp-dark').click()
        assert.equal(await visible(page, '#stimma-appearance-1 [when="light"] stimma-media'), 0)
        assert.ok(await visible(page, '#stimma-appearance-1 [when="dark"] stimma-media') > 0)
        await first.locator('label.sp-light').click()
        assert.equal(await visible(page, '#stimma-appearance-1 [when="dark"] stimma-media'), 0)
        assert.ok(await visible(page, '#stimma-appearance-1 [when="light"] stimma-media') > 0)

        // Never both: no light and dark of the same thing visible together.
        assert.equal(await visible(page, '[when="light"] stimma-media, [when="dark"] stimma-media'), 2)
        assert.deepEqual(errors, [])
        await page.close()
      }
    } finally {
      await browser.close()
    }
  })
}
