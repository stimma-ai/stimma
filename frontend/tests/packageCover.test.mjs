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
(run_root / 'a-very-long-file-name-that-would-otherwise-be-cut-off-in-a-narrow-column.bin').write_bytes(b'\\0' * 10)

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

const LONG = 'a-very-long-file-name-that-would-otherwise-be-cut-off-in-a-narrow-column.bin'
const item = (page, name) => page.locator('.sp-area .sp-item', { has: page.locator('.sp-name', { hasText: new RegExp('^' + name.replace(/\./g, '\\.') + '$') }) })
const crumbs = page => page.locator('.sp-crumbs .sp-crumb').allTextContents()
const facts = page => page.locator('.sp-facts').textContent()
const names = page => page.locator('.sp-area .sp-item .sp-name').allTextContents()
// Nothing in the browser is wider than the browser: no clipping, no overflow.
async function fits(page) {
  return page.evaluate(() => {
    const box = document.querySelector('.sp-browser').getBoundingClientRect()
    const bad = []
    for (const el of document.querySelectorAll('.sp-browser *')) {
      const r = el.getBoundingClientRect()
      if (r.width && (r.right > box.right + 1 || r.left < box.left - 1)) bad.push(el.className + ' ' + r.left + '..' + r.right)
    }
    return bad
  })
}

test('the package cover’s file browser actually works', async () => {
  const dir = renderRealCover()
  const source = readFileSync(join(dir, 'index.html'), 'utf8')
  assert.match(source, /stimma-files/)
  // Text travels inside the page, so the viewer works from a double-clicked file.
  assert.match(source, /class="sp-src">hello<\/script>/)

  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 900 }, acceptDownloads: false })
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    await page.goto(pathToFileURL(join(dir, 'index.html')).href)
    await page.waitForFunction(() => window.__stimmaKit === true)

    // Compact by default: the row states the facts, the browser stays shut.
    assert.equal(await page.locator('.sp-browser').isVisible(), false)
    assert.match(await page.locator('.sp-browse').textContent(), /View contents/)
    assert.equal(await page.locator('.sp-zip').count(), 0)

    // Open: a list of the root folder, folders first, with the crumb naming the root.
    await page.locator('.sp-browse').click()
    assert.equal(await page.locator('.sp-tree').isVisible(), false, 'the static tree is the data, not the UI')
    assert.deepEqual(await crumbs(page), ['files.zip'])
    assert.deepEqual(await names(page), ['nested', LONG, 'Contents.json', 'mark.svg', 'notes.txt'])
    assert.equal(await page.locator('.sp-seg button[aria-pressed=true]').textContent(), 'List')
    assert.deepEqual(await fits(page), [])

    // One click drills into a folder; the crumb bar follows; a crumb goes back.
    // And the box never changes height as you move around.
    const height = async () => (await page.locator('.sp-browser').boundingBox()).height
    const steady = await height()
    await item(page, 'nested').click()
    assert.equal(await height(), steady)
    assert.deepEqual(await crumbs(page), ['files.zip', 'nested'])
    assert.deepEqual(await names(page), ['big.png', 'small.png'])
    await page.locator('.sp-crumb', { hasText: /^files\.zip$/ }).click()
    assert.deepEqual(await crumbs(page), ['files.zip'])

    // A file opens in place, at its real dimensions, and Left/Right step between files.
    await item(page, 'nested').click()
    await item(page, 'small.png').click()
    assert.equal(await page.locator('.sp-area').isVisible(), false)
    assert.deepEqual(await crumbs(page), ['files.zip', 'nested', 'small.png'])
    await page.waitForFunction(() => /32 × 32/.test(document.querySelector('.sp-facts').textContent))
    assert.match(await facts(page), /^PNG · 32 × 32 · /)
    assert.equal(await page.locator('.sp-view img').getAttribute('src'), 'files/nested/small.png')
    assert.equal(await page.locator('.sp-vpos').textContent(), '2 of 2')
    assert.equal(await height(), steady)
    await page.keyboard.press('ArrowLeft')
    await page.waitForFunction(() => /256 × 256/.test(document.querySelector('.sp-facts').textContent))
    assert.equal(await page.locator('.sp-vpos').textContent(), '1 of 2')
    assert.equal(await page.getByRole('button', { name: 'Previous file' }).isDisabled(), true)
    await page.getByRole('button', { name: 'Next file' }).click()
    assert.deepEqual(await crumbs(page), ['files.zip', 'nested', 'small.png'])
    assert.deepEqual(await fits(page), [])

    // Escape backs out to the folder, with focus on the file you were viewing.
    await page.keyboard.press('Escape')
    assert.deepEqual(await crumbs(page), ['files.zip', 'nested'])
    assert.equal(await page.evaluate(() => document.activeElement.querySelector('.sp-name').textContent), 'small.png')
    // The crumb backs out of a file too, all the way up.
    await item(page, 'big.png').click()
    await page.locator('.sp-crumb', { hasText: /^files\.zip$/ }).click()
    assert.deepEqual(await crumbs(page), ['files.zip'])

    // JSON is readable: inlined at write time, pretty-printed at read time.
    await item(page, 'Contents.json').click()
    const json = await page.locator('.sp-code').textContent()
    assert.match(json, /^\{\n {2}"images": \[\n {4}\{\n {6}"idiom": "universal"/)
    assert.match(json, /"author": "stimma"/)
    assert.match(await facts(page), /^JSON · /)
    await page.keyboard.press('Escape')

    // Plain text too, from a file:// page where fetch() would be blocked.
    await item(page, 'notes.txt').click()
    assert.equal(await page.locator('.sp-code').textContent(), 'hello')
    await page.keyboard.press('Escape')

    // SVG stays rendered without a source/preview toggle.
    await item(page, 'mark.svg').click()
    assert.equal(await page.locator('.sp-view img').getAttribute('src'), 'files/mark.svg')
    assert.equal(await page.locator('.sp-code').count(), 0)
    assert.equal(await page.locator('.sp-src-toggle').count(), 0)
    await page.keyboard.press('Escape')

    // Something with no viewer says so, and a long name wraps instead of vanishing.
    await item(page, LONG).click()
    assert.match(await page.locator('.sp-blank').textContent(), /No preview/)
    assert.deepEqual(await fits(page), [])
    await page.keyboard.press('Escape')

    // The keyboard drives the listing: arrows move, Enter opens, Backspace goes up.
    await item(page, 'nested').focus()
    await page.keyboard.press('ArrowDown')
    assert.equal(await page.evaluate(() => document.activeElement.querySelector('.sp-name').textContent), LONG)
    await page.keyboard.press('ArrowUp')
    await page.keyboard.press('Enter')
    assert.deepEqual(await crumbs(page), ['files.zip', 'nested'])
    await page.keyboard.press('Backspace')
    assert.deepEqual(await crumbs(page), ['files.zip'])

    // Icons view is the same folder as tiles; a viewer is the same viewer.
    await page.locator('.sp-seg button', { hasText: 'Icons' }).click()
    assert.equal(await page.locator('.sp-area').getAttribute('class'), 'sp-area sp-icons')
    assert.deepEqual(await names(page), ['nested', LONG, 'Contents.json', 'mark.svg', 'notes.txt'])
    assert.deepEqual(await fits(page), [])
    await page.screenshot({ path: '/tmp/package-browser-icons.png', clip: { x: 0, y: 0, width: 1000, height: 900 } })
    await item(page, 'nested').click()
    await item(page, 'big.png').click()
    await page.waitForFunction(() => /256 × 256/.test(document.querySelector('.sp-facts').textContent))
    await page.screenshot({ path: '/tmp/package-browser-viewer.png', clip: { x: 0, y: 0, width: 1000, height: 900 } })
    await page.keyboard.press('Escape')
    assert.equal(await page.locator('.sp-area').getAttribute('class'), 'sp-area sp-icons', 'the view mode survives a viewer')

    // No per-row download: a file you can open has its download in the viewer.
    assert.equal(await page.locator('.sp-area .sp-dl').count(), 0)

    // Escape from the listing closes the browser and lands on the summary.
    await item(page, 'big.png').focus()
    await page.keyboard.press('Escape')
    assert.equal(await page.locator('.sp-browser').isVisible(), false)
    assert.equal(await page.evaluate(() => document.activeElement.tagName), 'SUMMARY')

    // Reopening keeps your place. Focus rings are keyboard-only: a mouse
    // click that lands focus on the first item of a folder draws no ring.
    await page.locator('.sp-browse').click()
    assert.deepEqual(await crumbs(page), ['files.zip', 'nested'])
    await page.locator('.sp-crumb', { hasText: /^files\.zip$/ }).click()
    await item(page, 'nested').click()
    assert.equal(await page.evaluate(() => document.activeElement.querySelector('.sp-name').textContent), 'big.png')
    assert.equal(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'none')
    await page.keyboard.press('ArrowDown')
    assert.equal(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'solid')
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
    await item(page, 'notes.txt').click()
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
    const page = await context.newPage({ viewport: { width: 1000, height: 900 } })
    await page.goto(pathToFileURL(join(dir, 'index.html')).href)
    assert.equal(await page.locator('.sp-tree').isVisible(), false)
    await page.locator('.sp-browse').click()
    assert.equal(await page.locator('.sp-tree').isVisible(), true)
    const row = page.locator('li[data-name="notes.txt"] > .sp-row')
    assert.equal(await row.isVisible(), true)
    assert.equal(await row.locator('.sp-dl').getAttribute('href'), 'files/notes.txt?download=1')
    assert.equal(await page.locator('li[data-name="nested"] li[data-name="big.png"]').count(), 1)
    await page.screenshot({ path: '/tmp/package-browser-noscript.png', clip: { x: 0, y: 0, width: 1000, height: 900 } })
  } finally {
    await browser.close()
  }
})

test('nothing in the page shows a scrollbar track, and the code pane scrolls quietly', async () => {
  const dir = renderRealCover()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 900 } })
    await page.goto(pathToFileURL(join(dir, 'index.html')).href)
    await page.waitForFunction(() => window.__stimmaKit === true)
    const style = await page.evaluate(() => {
      const s = getComputedStyle(document.querySelector('.sp-area'))
      return [s.scrollbarWidth, s.scrollbarColor]
    })
    assert.equal(style[0], 'thin')
    assert.match(style[1], /transparent|rgba\(0, 0, 0, 0\)$/)
  } finally {
    await browser.close()
  }
})
