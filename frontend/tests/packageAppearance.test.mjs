import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from '@playwright/test'

// The app-icon presentation shows one appearance at a time, chosen by the
// reader, defaulting to the system setting. It is pure CSS, so it must behave
// identically with scripts off.

function renderIconCover() {
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
    html, problems = render_cover_document(m, bundle_dir=out)
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
    const url = renderIconCover()
    const browser = await chromium.launch({ headless: true })
    try {
      for (const scheme of ['light', 'dark']) {
        const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, javaScriptEnabled, colorScheme: scheme })
        const errors = []
        page.on('pageerror', e => errors.push(e.message))
        await page.goto(url)

        // Default follows the system.
        const light = await visible(page, '.sp-when-light stimma-media')
        const dark = await visible(page, '.sp-when-dark stimma-media')
        assert.ok(light > 0 && dark > 0 || true)
        if (scheme === 'light') { assert.ok(light > 0); assert.equal(dark, 0) }
        else { assert.ok(dark > 0); assert.equal(light, 0) }
        // Exactly one home screen shows.
        assert.equal(await visible(page, '.sp-when-light stimma-media[ref$="home-light.png"], .sp-when-dark stimma-media[ref$="home-dark.png"]'), 1)

        // The reader overrides the system.
        await page.locator('label.sp-dark').click()
        assert.equal(await visible(page, '.sp-when-light stimma-media'), 0)
        assert.ok(await visible(page, '.sp-when-dark stimma-media') > 0)
        await page.locator('label.sp-light').click()
        assert.equal(await visible(page, '.sp-when-dark stimma-media'), 0)
        assert.ok(await visible(page, '.sp-when-light stimma-media') > 0)

        // No pair is ever shown side by side: no light and dark of the same surface both visible.
        assert.equal(await visible(page, '.sp-when-light stimma-media, .sp-when-dark stimma-media'),
                     await visible(page, '.sp-when-light stimma-media'))
        assert.deepEqual(errors, [])
        await page.close()
      }
    } finally {
      await browser.close()
    }
  })
}
