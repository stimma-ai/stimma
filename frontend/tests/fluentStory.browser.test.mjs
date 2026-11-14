import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The main Fluent story through Tool View's prompt card as ToolView wires it: the editor,
// its Fluent menu, its marks, the lines under it and the slot's picker together, against routes
// that answer in the backend's shapes (routes/prompt_programs.py `public`, /pools, /suggest,
// /add). Type a plain prompt, make a slot from an underline, pin a variant in its picker, add
// light from the row under the text, leave it out, set the detail level, and generate.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/fluentStory.ts', import.meta.url)), name: 'FluentStoryTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

const MEN = ['young man of Korean descent with a buzz cut', 'lanky young man of Irish descent with a side part', 'young man of Nigerian descent with shoulder-length curls']
const LIGHTS = ['warm desk lamp glow', 'soft afternoon window light', 'cool overhead fluorescent light']
const VARIANTS = { young_man: MEN, light: LIGHTS }

// A stand-in backend: one choice per slot, built into the editor's view of a program as
// `public()` builds it; each slot's variants come with /pools.
function readSlots(prompt) {
  const slots = []
  const choices = []
  const re = /<([^<>{}[\]|#:=\n]+)>/g
  let m
  let n = 0
  while ((m = re.exec(prompt))) {
    n++
    const words = m[1]
    const span = [m.index, m.index + m[0].length]
    const id = words.replace(/\W+/g, '_')
    const label = words === 'light' ? 'Lighting' : words === 'young man' ? 'Young man' : words
    slots.push({ id, n, kind: words === 'young man' ? 'person' : words === 'light' ? 'light' : 'free', label, words, span, line: 1 })
    choices.push({ id, kind: 'variants', label, slot: id })
  }
  return { key: slots.length ? `k:${slots.map(s => s.words).join('|')}` : null, slots, choices }
}
const variantsOf = (id, words) => (VARIANTS[id] || [`a ${words}`, `an old ${words}`, `a small ${words}`]).map(text => ({ text, seeds: {} }))

async function open(t, { theme = 'dark', width = 900, height = 760, mobile = false, start = '', dev = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2, hasTouch: mobile, isMobile: mobile, colorScheme: theme })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const calls = { prepare: [], suggest: [], add: [], pools: [] }
  // The slots the server has read, by their words: 'working' while it reads one, then 'read'.
  const reads = new Map()
  await page.route('**/*', async route => {
    const url = route.request().url()
    const body = route.request().method() === 'POST' ? route.request().postDataJSON() : null
    const json = data => route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    if (url.endsWith('/prompt-programs/suggest')) {
      calls.suggest.push(body)
      const i = body.prompt.indexOf('young man')
      const vary = i < 0 || body.prompt[i - 1] === '<' ? [] : [{ from: i, to: i + 9, text: 'young man' }]
      return json({ vary, adds: [{ name: 'light', label: 'light' }, { name: 'camera', label: 'camera' }] })
    }
    if (url.endsWith('/prompt-programs/add')) {
      calls.add.push(body)
      await new Promise(r => setTimeout(r, 300))
      const next = `${body.prompt}, lit by <${body.name}>`
      return json({ prompt: next, slot: { from: next.length - body.name.length - 2, to: next.length } })
    }
    if (url.endsWith('/prompt-programs/prepare')) {
      calls.prepare.push(body)
      const read = readSlots(body.prompt)
      if (!read.key) return json({ key: null, slots: [], choices: [] })
      // As slots.prepare answers: at once, every slot from the parse, each `reading` until it
      // is read (a slot read for an earlier prompt is read here too). Only a prepare that isn't
      // cache-only starts reading, in the background (`working`) for 700 ms.
      if (!body.cache_only) for (const sl of read.slots) if (!reads.has(sl.words)) {
        reads.set(sl.words, 'working')
        setTimeout(() => reads.set(sl.words, 'read'), 700)
      }
      const done = new Set(read.slots.filter(sl => reads.get(sl.words) === 'read').map(sl => sl.id))
      if (done.size < read.slots.length) {
        const slots = read.slots.map(sl => done.has(sl.id) ? { ...sl, state: 'ready' }
          : { id: sl.id, n: sl.n, kind: 'free', label: sl.words, words: sl.words, span: sl.span, line: sl.line, state: 'reading' })
        const choices = read.choices.filter(c => done.has(c.slot))
        return json({ key: read.key, slots, choices, reading: true, working: read.slots.some(sl => reads.get(sl.words) === 'working') })
      }
      return json({ ...read, slots: read.slots.map(s => ({ ...s, state: 'ready' })), reading: false, working: false, example: 'A dorm room with a 24-year-old Korean man', seconds: 0.7,
        ...(body.include_program ? { picks: [{ id: 'young_man', kind: 'variants' }], example: 'Dorm room with a 21-year-old man', readings: { slots: [{ n: 1, kind: 'person', label: 'Young man' }] } } : {}) })
    }
    if (url.endsWith('/prompt-programs/pools')) {
      calls.pools.push(body)
      const read = readSlots(body.prompt)
      return json({ choices: Object.fromEntries(read.slots.map((sl) => {
        const variants = variantsOf(sl.id, sl.words)
        return [sl.id, { kind: 'variants', state: 'ready', more: false, variants, options: variants.map(v => v.text), chosen: body.choices?.[sl.id] || null }]
      })), more: [] })
    }
    if (url.endsWith('/prompt-programs/preview')) return json({ prompt: 'A dorm room with a 21-year-old Irish man with a buzz cut', draws: [{ id: 'young_man', value: MEN[1] }] })
    if (url.endsWith('/api/generate')) return json(body)
    if (url.includes('/api/')) return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    return route.fulfill({ contentType: 'text/html', body: `<html data-theme="${theme}" class="${theme}"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body class="bg-app"><script>window.START = ${JSON.stringify(start)}; window.DEV = ${dev}</script><div id="app"></div></body></html>` })
  })
  await page.goto('http://fluent-story.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.locator('.cm-content').waitFor()
  t.after(() => assert.deepEqual(errors, []))
  const shot = async file => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${file}.png` }) }
  const card = page.locator('[data-picker-body]')
  const lines = page.locator('[data-slot-list]')
  const mark = n => page.locator(`[data-slot-n="${n}"]`)
  return { page, calls, shot, card, lines, mark, editor: page.locator('.cm-content') }
}

const text = page => page.evaluate(() => window.text())

async function story(t, opts = {}) {
  const tag = opts.tag || 'desktop-dark'
  const { page, calls, shot, card, lines, mark, editor } = await open(t, opts)
  const tap = opts.mobile ? (l => l.tap()) : (l => l.click())

  // A plain prompt: Suggest underlines what could vary and offers what is absent.
  await editor.click()
  await page.keyboard.type('dorm room with a young man')
  await expect(page.locator('.cm-could-vary')).toHaveText('young man', { timeout: 4000 })
  await expect(page.locator('[data-slot-add]')).toHaveText(['light', 'camera'])
  assert.equal(calls.suggest.at(-1).prompt, 'dorm room with a young man')
  assert.equal(calls.suggest.at(-1).project_id, 7)
  // Nothing varies yet: no rows.
  await expect(lines.locator('[data-row]')).toHaveCount(0)
  await expect(page.locator('[data-program-choices]')).toHaveCount(0)
  await shot(`${tag}-1-underlined`)

  // Vary this wraps it and its row opens while the slot is read, then fills.
  await page.locator('.cm-could-vary').click()
  await tap(page.locator('[data-vary]'))
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
  await shot(`${tag}-2-writing`)
  await expect(card.locator(`[data-variant="${MEN[0]}"]`)).toBeVisible({ timeout: 4000 })
  await expect(card.locator('[data-any] svg')).toHaveCount(1)
  await shot(`${tag}-3-picker`)

  // Pin a variant: the slot fills, and its row says what it is.
  await tap(card.locator(`[data-variant="${MEN[1]}"]`))
  await expect(page.locator('[data-row="young_man"]')).toContainText(MEN[1])
  await expect(mark(1)).toHaveAttribute('data-slot-look', 'restricted')
  await shot(`${tag}-4-chosen`)
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)

  // + light writes it into the prompt as a slot and opens it.
  await tap(page.locator('[data-slot-add="light"]'))
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>, lit by <light>')
  assert.deepEqual(calls.add.at(-1), { project_id: 7, prompt: 'dorm room with a <young man>', name: 'light' })
  await expect(card.locator(`[data-variant="${LIGHTS[0]}"]`)).toBeVisible({ timeout: 4000 })
  await expect(page.locator('[data-row-wrap="light"][data-open]')).toHaveCount(1)
  await expect(page.locator('[data-slot-add]')).toHaveText(['camera'], { timeout: 4000 })
  await shot(`${tag}-5-light`)

  // Keep my words.
  await tap(card.locator('[data-keep-words]'))
  await expect(page.locator('[data-row="light"]')).toContainText('“light”')
  await expect(mark(2)).toHaveAttribute('data-slot-look', 'words')
  await shot(`${tag}-6-keep-words`)

  // A row opened from the slot in the text closes on Esc, though focus stays in the prompt.
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)
  await mark(1).click()
  await expect(page.locator('[data-row-wrap="young_man"][data-open]')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)

  // Detail level High from the Fluent menu.
  await tap(page.locator('[data-fluent-chip]'))
  const menu = page.locator('[data-fluent-menu]')
  await expect(menu.locator('[data-detail-line]')).toContainText('Adds a little')
  await tap(menu.getByRole('radio', { name: 'High' }))
  await expect(menu.locator('[data-detail-line]')).toContainText('Adds a lot')
  await shot(`${tag}-7-menu`)
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)

  // Generate carries the choices and the level.
  await tap(page.locator('[data-generate]'))
  await expect.poll(() => page.evaluate(() => window.sent.length)).toBe(1)
  const [body] = await page.evaluate(() => window.sent)
  assert.equal(body.parameters.prompt, 'dorm room with a <young man>, lit by <light>')
  assert.deepEqual(body.promptOptions.program, { enabled: true, choices: { young_man: { values: [MEN[1]] }, light: { as_written: true } } })
  assert.equal(body.promptOptions.autoImprove.enabled, true)
  assert.equal(body.promptOptions.autoImprove.level, 'expand')
  return { page, calls }
}

test('the main story, desktop dark', async t => { await story(t) })
test('the main story, desktop light', async t => { await story(t, { theme: 'light', tag: 'desktop-light' }) })
test('the main story, phone dark', async t => { await story(t, { width: 390, height: 844, mobile: true, tag: 'phone-dark' }) })
test('the main story, phone light', async t => { await story(t, { width: 390, height: 844, mobile: true, theme: 'light', tag: 'phone-light' }) })

// A look-up never starts reading: it finds a slot just typed `reading`, with nothing reading
// it. The prompt is read once the user pauses in the box, leaves it, or generates, and only once.
async function typeSlot(t) {
  const o = await open(t)
  await o.editor.click()
  await o.page.keyboard.type('a <young man')
  await o.page.keyboard.type('>')
  await expect.poll(() => text(o.page)).toBe('a <young man>')
  // The look-up has found it unread: the slot shows as still being written, and nothing asked to read it.
  await expect(o.mark(1)).toHaveAttribute('data-slot-look', 'writing', { timeout: 2000 })
  await o.page.waitForTimeout(500)
  assert.deepEqual(o.calls.prepare.filter(b => !b.cache_only), [])
  return o
}
const reads = calls => calls.prepare.filter(b => !b.cache_only).map(b => b.prompt)
async function filledIn({ mark, calls }) {
  await expect(mark(1)).toHaveAttribute('data-slot-look', 'varying', { timeout: 4000 })
  assert.deepEqual(reads(calls), ['a <young man>'])
}

test('a slot typed is read once the user pauses in the prompt', async t => {
  const o = await typeSlot(t)
  await expect.poll(() => reads(o.calls), { timeout: 2500 }).toEqual(['a <young man>'])
  assert.ok(await o.page.evaluate(() => document.querySelector('[data-prompt-editor]').contains(document.activeElement)))
  await filledIn(o)
  await o.page.waitForTimeout(1600)
  assert.deepEqual(reads(o.calls), ['a <young man>'])
})

test('a slot typed is read when the user leaves the prompt', async t => {
  const o = await typeSlot(t)
  await o.page.mouse.click(880, 740)
  await expect.poll(() => reads(o.calls), { timeout: 500 }).toEqual(['a <young man>'])
  await filledIn(o)
})

test('a slot typed is read when the user generates at once', async t => {
  const o = await typeSlot(t)
  await o.page.evaluate(() => window.generate())
  await expect.poll(() => reads(o.calls), { timeout: 500 }).toEqual(['a <young man>'])
  await expect.poll(() => o.page.evaluate(() => window.sent.length)).toBe(1)
  await filledIn(o)
  await o.page.waitForTimeout(1600)
  assert.deepEqual(reads(o.calls), ['a <young man>'])
})

test('the developer view shows the slot reading and the picks made from it', async t => {
  const { page, card } = await open(t, { start: 'dorm room with a <young man>', dev: true })
  await expect(page.locator('[data-slot-n="1"]')).toHaveAttribute('data-slot-look', 'varying', { timeout: 4000 })
  await expect(card).toHaveCount(0)
  await page.locator('[data-fluent-chip]').click()
  await page.getByRole('button', { name: 'Show readings' }).click()
  const dialog = page.locator('[data-program-debug]')
  await expect(dialog).toContainText('"young_man"')
  await expect(dialog.locator('[data-reading]')).toContainText('"kind": "person"')
  await expect(dialog).toContainText('A dorm room with a 21-year-old Irish man')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/dev-dialog.png` })
})

test('the developer view of a prompt with nothing that varies says so', async t => {
  const { page } = await open(t, { start: 'a lighthouse at dusk', dev: true })
  await page.waitForTimeout(600)
  await page.locator('[data-fluent-chip]').click()
  await page.getByRole('button', { name: 'Show readings' }).click()
  await expect(page.locator('[data-program-debug]')).toContainText('Nothing in this prompt varies')
})

test('Keep from this on a result tile and in the menu, only for images made from slots', async t => {
  const { page } = await open(t)
  const tiles = page.locator('[data-results] .job-tile')
  await expect(tiles).toHaveCount(2)
  await expect(tiles.nth(0).locator('[data-keep-button]')).toHaveAttribute('title', 'Keep from this')
  await expect(tiles.nth(1).locator('[data-keep-button]')).toHaveCount(0)
  await tiles.nth(0).locator('[data-keep-button]').click()
  assert.deepEqual(await page.evaluate(() => window.menuActions(5)), ['Keep from this'])
  assert.deepEqual(await page.evaluate(() => window.menuActions(6)), [])
  await page.evaluate(() => window.runMenuAction(5))
  assert.deepEqual(await page.evaluate(() => window.kept), [['tile', 1], ['menu', 1]])
})

// Touch: on a phone each row and the + ideas are full-size targets (44px), and no two overlap.
const FOUR = 'dorm room with a <young man> and his <pet>, lit by <light>, at a <late-night diner on the edge of town>'
const MIN = 44

async function measure(locator) {
  return locator.evaluateAll(els => els.map(el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } }))
}
const overlaps = (a, b) => a.x < b.x + b.w - 0.5 && b.x < a.x + a.w - 0.5 && a.y < b.y + b.h - 0.5 && b.y < a.y + a.h - 0.5

for (const theme of ['dark', 'light']) {
  test(`on a phone, the rows and the + ideas are touch-sized, ${theme}`, async t => {
    const { page, card, lines, mark, shot } = await open(t, { width: 390, height: 844, mobile: true, theme, start: FOUR })
    await expect(mark(2)).toHaveAttribute('data-slot-look', 'varying', { timeout: 4000 })
    await mark(2).tap()
    await card.locator('[data-variant="an old pet"]').tap()
    await shot(`phone-${theme}-picker`)
    await page.keyboard.press('Escape')
    await expect(card).toHaveCount(0)
    await expect(page.locator('[data-slot-add]')).toHaveText(['camera'], { timeout: 4000 })
    await shot(`phone-${theme}-rows`)
    const rows = await measure(lines.locator('[data-row]'))
    const adds = await measure(page.locator('[data-slot-add]'))
    assert.equal(rows.length, 4)
    for (const b of [...rows, ...adds]) assert.ok(b.w >= MIN && b.h >= MIN, `target ${b.w}x${b.h}`)
    for (const b of rows) assert.ok(b.x >= 0 && b.x + b.w <= 390, `on screen: ${JSON.stringify(b)}`)
    const all = [...rows, ...adds]
    for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++) {
      assert.ok(!overlaps(all[i], all[j]), `targets overlap: ${JSON.stringify(all[i])} ${JSON.stringify(all[j])}`)
    }
  })
}

test('on a desktop, rows stay compact', async t => {
  const { page, card, lines, mark } = await open(t, { start: FOUR })
  await expect(mark(2)).toHaveAttribute('data-slot-look', 'varying', { timeout: 4000 })
  await mark(2).click()
  await card.locator('[data-variant="an old pet"]').click()
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)
  for (const b of await measure(lines.locator('[data-row="pet"]'))) assert.ok(b.h <= 30, `desktop row ${b.h}px`)
  for (const b of await measure(page.locator('[data-slot-add]'))) assert.ok(b.h <= 28, `desktop add ${b.h}px`)
})

// The prompt tips, opened from the Fluent menu: what you can type, slots first, in each way of sending.
async function openTips(page, way) {
  await page.locator('[data-fluent-chip]').click()
  const menu = page.locator('[data-fluent-menu]')
  if (way) await menu.getByRole('radio', { name: way }).click()
  await page.getByRole('button', { name: 'Prompt tips' }).click()
  const tips = page.locator('[data-prompt-tips]')
  await expect(tips).toBeVisible()
  return tips
}

for (const [label, opts] of [['desktop dark', {}], ['desktop light', { theme: 'light' }], ['phone dark', { width: 390, height: 844, mobile: true }], ['phone light', { width: 390, height: 844, mobile: true, theme: 'light' }]]) {
  test(`the prompt tips cover slots first, then what else you can type, ${label}`, async t => {
    const { page, shot } = await open(t, opts)
    const tips = await openTips(page)
    const sections = await tips.locator('section h4').allInnerTexts()
    assert.deepEqual(sections, ['Vary any part', 'Choose what it can be', 'Keep from this', 'Detail level', 'Lists', 'Saved wildcards and segments', 'Comment lines', 'Exact text'])
    const text = await tips.innerText()
    for (const s of ['Vary this', 'press <', '+ light', 'Keep my words', 'Keep from this', 'Yours', 'Medium', 'High'])
      assert.ok(text.includes(s), `tips mention ${s}`)
    await expect(tips.locator('[data-tip-example="slot"]')).toContainText('<young man>')
    // No mechanics, no old features, no em dashes.
    assert.doesNotMatch(text, /Try different|smart wildcard|LoRA|parameters|—/i)
    // Slots wear the editor's slot color, apart from lists and saved names.
    const color = sel => tips.locator(sel).first().evaluate(el => getComputedStyle(el).color)
    const slot = await color('[data-tip-example="slot"] [data-tone="slot"]')
    const list = await color('[data-tone="list"]')
    const named = await color('[data-tone="name"]')
    assert.notEqual(slot, list)
    assert.notEqual(slot, named)
    const editorSlot = await page.evaluate(() => {
      const probe = document.createElement('span'); probe.style.color = 'rgb(var(--color-selection-rgb))'; document.body.appendChild(probe)
      const c = getComputedStyle(probe).color; probe.remove(); return c
    })
    assert.equal(slot, editorSlot)
    // On screen, and scrolls rather than running off it.
    const box = await tips.boundingBox()
    const vp = page.viewportSize()
    assert.ok(box.x >= 0 && box.x + box.width <= vp.width && box.y >= 0 && box.y + box.height <= vp.height + 0.5, `tips at ${JSON.stringify(box)}`)
    await expect(tips.locator('[data-tips-way]')).toHaveCount(0)
    await shot(`tips-${label.replace(' ', '-')}-fluent`)
    await tips.evaluate(el => { el.scrollTop = el.scrollHeight })
    await shot(`tips-${label.replace(' ', '-')}-fluent-end`)
  })
}

test('the prompt tips say what Direct and Raw do with the rest', async t => {
  const { page, shot } = await open(t, { start: 'dorm room with a <young man>' })
  let tips = await openTips(page, 'Direct')
  await expect(tips.locator('[data-tips-way]')).toHaveText('Direct fills in lists and saved wildcards. Slots are sent as their words. Choose Fluent to vary them.')
  await expect(tips.locator('section h4').first()).toHaveText('Vary any part')
  await shot('tips-direct')
  await page.keyboard.press('Escape')
  await page.mouse.click(5, 5)
  await expect(tips).toHaveCount(0)
  tips = await openTips(page, 'Raw')
  await expect(tips.locator('[data-tips-way]')).toHaveText('Raw sends your prompt exactly as typed. Choose Fluent or Direct to use the rest.')
  await shot('tips-raw')
})
