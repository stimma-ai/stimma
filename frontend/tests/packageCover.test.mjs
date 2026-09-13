import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from '@playwright/test'

// The cover is a real page with real behaviour, and the behaviour is the part
// that silently dies: a custom element's connectedCallback runs before its
// children are parsed, so a component that wires itself up there ships inert
// and looks fine in every screenshot. This drives the page the backend
// actually produces.

function renderRealCover() {
  const dir = mkdtempSync(join(tmpdir(), 'stimma-cover-'))
  const script = `
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, '.')
from packages.cover import render_cover_document
from packages.manifest import new_manifest, write_manifest

out = Path(${JSON.stringify('%DIR%')})
run_root = out / 'files'
(run_root / 'nested').mkdir(parents=True)
for name, size in (('big.png', 256), ('small.png', 32)):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((2, 2, size - 2, size - 2), fill=(240, 160, 30, 255))
    img.save(run_root / 'nested' / name)
(run_root / 'notes.txt').write_text('hello')

files = []
for path in sorted(run_root.rglob('*')):
    if path.is_file():
        rel = 'files/' + str(path.relative_to(run_root)).replace('\\\\', '/')
        files.append({'path': rel, 'hash': 'x', 'size': path.stat().st_size})

manifest = new_manifest(title='Behaviour fixture')
manifest['runs'] = [{
    'id': 'r1', 'recipe': {'id': 'fixture', 'version': 1, 'display_name': 'Fixture'},
    'inputs': {}, 'params': {}, 'root': 'files/', 'files': files,
}]
html, problems = render_cover_document(manifest)
assert not problems, problems
(out / 'index.html').write_text(html)
write_manifest(out, manifest)
`.replace('%DIR%', dir)
  execFileSync('uv', ['run', 'python', '-c', script], {
    cwd: new URL('../../backend', import.meta.url).pathname,
    stdio: ['ignore', 'ignore', 'inherit'],
  })
  return dir
}

test('the package cover’s file browser actually works', async () => {
  const dir = renderRealCover()
  assert.match(readFileSync(join(dir, 'index.html'), 'utf8'), /stimma-files/)

  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 900 } })
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    await page.goto(pathToFileURL(join(dir, 'index.html')).href)
    await page.waitForFunction(() => window.__stimmaKit === true)

    // Folding: a folder responds to the mouse and says so for a screen reader.
    const folder = page.locator('li.sp-dir > .sp-row').first()
    await folder.click()
    assert.equal(await page.evaluate(() =>
      document.querySelector('li.sp-dir').classList.contains('sp-collapsed')), true)
    assert.equal(await folder.getAttribute('aria-expanded'), 'false')
    assert.equal(await page.evaluate(() =>
      document.querySelector('li.sp-dir > ul').offsetParent !== null), false)

    // And to the keyboard.
    await folder.focus()
    await page.keyboard.press('Enter')
    assert.equal(await page.evaluate(() =>
      document.querySelector('li.sp-dir').classList.contains('sp-collapsed')), false)

    // Preview: an image opens full size and reports its real dimensions.
    await page.locator('li.sp-previewable > .sp-row').first().click()
    // The name is there at once; the dimensions land with the image.
    assert.match(await page.locator('.sp-lightbox figcaption').textContent(), /big\.png/)
    await page.waitForFunction(() =>
      /\d+ × \d+/.test(document.querySelector('.sp-lightbox figcaption').textContent))
    assert.match(await page.locator('.sp-lightbox figcaption').textContent(), /256 × 256/)
    assert.equal(await page.evaluate(() =>
      getComputedStyle(document.querySelector('.sp-lightbox')).display), 'flex')

    // Escape closes it and lets go of the image.
    await page.keyboard.press('Escape')
    assert.equal(await page.evaluate(() => {
      const box = document.querySelector('.sp-lightbox')
      return box.classList.contains('sp-open') || box.querySelector('img').getAttribute('src')
    }), null)

    // A non-image row has no preview to open.
    await page.locator('li:not(.sp-previewable) > .sp-row').last().click()
    assert.equal(await page.evaluate(() =>
      document.querySelector('.sp-lightbox').classList.contains('sp-open')), false)

    assert.deepEqual(errors, [])
  } finally {
    await browser.close()
  }
})
