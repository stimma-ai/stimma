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
# Compact on disk, so pretty-printing in the viewer is visible rather than assumed.
(run_root / 'Contents.json').write_text(json.dumps(
    {'images': [{'idiom': 'universal', 'scale': '2x', 'size': '60x60'}],
     'info': {'author': 'stimma', 'version': 1}}, separators=(',', ':')))
(run_root / 'mark.svg').write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="10" fill="#2dd4bf"/></svg>')

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
html, problems = render_cover_document(manifest, bundle_dir=out)
assert not problems, problems
(out / 'index.html').write_text(html)
# The same cover rendered without the files on disk: nothing to inline.
html, problems = render_cover_document(manifest)
assert not problems, problems
(out / 'nosource.html').write_text(html)
write_manifest(out, manifest)
`.replace('%DIR%', dir)
  execFileSync('uv', ['run', 'python', '-c', script], {
    cwd: new URL('../../backend', import.meta.url).pathname,
    stdio: ['ignore', 'ignore', 'inherit'],
  })
  return dir
}

const rowOf = name => `li[data-name="${name}"] > .sp-row`
const selected = page => page.evaluate(() => {
  const row = document.querySelector('.sp-row.sp-sel')
  return row ? row.parentElement.getAttribute('data-name') : null
})

test('the package cover’s file browser actually works', async () => {
  const dir = renderRealCover()
  const source = readFileSync(join(dir, 'index.html'), 'utf8')
  assert.match(source, /stimma-files/)
  // The overlay is gone: everything happens inside the page now.
  assert.equal(/sp-lightbox/.test(source), false)

  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, acceptDownloads: false })
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    await page.goto(pathToFileURL(join(dir, 'index.html')).href)
    await page.waitForFunction(() => window.__stimmaKit === true)

    // Compact by default: the row states the facts, the browser stays shut.
    assert.equal(await page.locator('.sp-tree').isVisible(), false)
    assert.equal(await page.locator('.sp-browser').isVisible(), false)
    assert.match(await page.locator('.sp-files-what').textContent(), /5 files/)
    assert.match(await page.locator('.sp-zip').textContent(), /Download files\.zip/)
    assert.equal(await page.locator('.sp-zip').getAttribute('href'), 'files.zip?download=1')

    // Toggling opens the browser, and it lands on something rather than a void.
    await page.locator('.sp-browse').click()
    assert.equal(await page.locator('.sp-tree').isVisible(), true)
    await page.waitForFunction(() => !!document.querySelector('.sp-row.sp-sel'))
    assert.equal(await selected(page), 'big.png')

    // An image shows at natural size, with the dimensions the file really has.
    await page.locator(rowOf('small.png')).click()
    assert.equal(await selected(page), 'small.png')
    await page.waitForFunction(() => /\d+ × \d+/.test(document.querySelector('.sp-vmeta').textContent))
    assert.match(await page.locator('.sp-view-head').textContent(), /small\.png/)
    assert.match(await page.locator('.sp-vmeta').textContent(), /32 × 32/)
    await page.locator(rowOf('big.png')).click()
    await page.waitForFunction(() => /256 × 256/.test(document.querySelector('.sp-vmeta').textContent))
    assert.equal(await page.locator('.sp-view img').getAttribute('src'), 'files/nested/big.png')

    // JSON is readable: inlined at write time, pretty-printed at read time.
    await page.locator(rowOf('Contents.json')).click()
    const json = await page.locator('.sp-code').textContent()
    assert.match(json, /^\{\n {2}"images": \[\n {4}\{\n {6}"idiom": "universal"/)
    assert.match(json, /"author": "stimma"/)

    // Plain text too, from a file:// page where fetch() would be blocked.
    await page.locator(rowOf('notes.txt')).click()
    assert.equal(await page.locator('.sp-code').textContent(), 'hello')

    // An SVG renders, and its markup is one toggle away — with the bytes intact.
    await page.locator(rowOf('mark.svg')).click()
    assert.equal(await page.locator('.sp-view img').getAttribute('src'), 'files/mark.svg')
    assert.equal(await page.locator('.sp-code').count(), 0)
    await page.locator('.sp-src-toggle').click()
    const svg = await page.locator('.sp-code').textContent()
    assert.match(svg, /<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/)
    assert.match(svg, /<\/svg>$/)
    await page.locator('.sp-src-toggle').click()
    assert.equal(await page.locator('.sp-code').count(), 0)

    // The arrows walk the tree; the pane follows. (Focus is on the toggle
    // button after that last click, and the viewer keeps its own keys.)
    await page.locator(rowOf('mark.svg')).click()
    await page.keyboard.press('ArrowDown')
    assert.equal(await selected(page), 'notes.txt')
    assert.match(await page.locator('.sp-view-head').textContent(), /notes\.txt/)
    await page.keyboard.press('ArrowUp')
    assert.equal(await selected(page), 'mark.svg')

    // A download is a download: it never moves the selection. (From a file://
    // page Chromium ignores the download attribute and would navigate, so the
    // navigation is blocked here — the kit's own handlers still run.)
    await page.evaluate(() => {
      window.__stop = ev => ev.preventDefault()
      document.addEventListener('click', window.__stop, true)
    })
    await page.locator(`${rowOf('notes.txt')} .sp-dl`).click()
    assert.equal(await selected(page), 'mark.svg')
    await page.evaluate(() => document.removeEventListener('click', window.__stop, true))

    // Folders fold by mouse and by keyboard, and say so for a screen reader.
    const folder = page.locator('li.sp-dir > .sp-row').first()
    await folder.click()
    assert.equal(await page.evaluate(() =>
      document.querySelector('li.sp-dir').classList.contains('sp-collapsed')), true)
    assert.equal(await folder.getAttribute('aria-expanded'), 'false')
    assert.equal(await page.locator(rowOf('big.png')).isVisible(), false)
    await page.keyboard.press('Enter')
    assert.equal(await page.evaluate(() =>
      document.querySelector('li.sp-dir').classList.contains('sp-collapsed')), false)

    // Escape puts it back to one quiet row.
    await page.keyboard.press('Escape')
    assert.equal(await page.locator('.sp-tree').isVisible(), false)
    assert.equal(await page.locator('.sp-files-what').isVisible(), true)

    assert.deepEqual(errors, [])
  } finally {
    await browser.close()
  }
})

test('a cover rendered without the files says so instead of failing', async () => {
  const dir = renderRealCover()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 900 } })
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    await page.goto(pathToFileURL(join(dir, 'nosource.html')).href)
    await page.waitForFunction(() => window.__stimmaKit === true)
    await page.locator('.sp-browse').click()
    await page.locator(rowOf('notes.txt')).click()
    assert.match(await page.locator('.sp-empty').textContent(), /Open the package/)
    assert.deepEqual(errors, [])
  } finally {
    await browser.close()
  }
})

test('the browser still opens with scripts off', async () => {
  const dir = renderRealCover()
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ javaScriptEnabled: false })
    const page = await context.newPage()
    await page.goto(pathToFileURL(join(dir, 'index.html')).href)
    assert.equal(await page.locator('.sp-tree').isVisible(), false)
    await page.locator('.sp-browse').click()
    assert.equal(await page.locator('.sp-tree').isVisible(), true)
    assert.equal(await page.locator(rowOf('notes.txt')).isVisible(), true)
    assert.equal(await page.locator(`${rowOf('notes.txt')} .sp-dl`).getAttribute('href'),
      'files/notes.txt?download=1')
  } finally {
    await browser.close()
  }
})
