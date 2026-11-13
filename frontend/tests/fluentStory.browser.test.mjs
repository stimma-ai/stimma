import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The main Fluent story through Tool View's prompt card as ToolView wires it: the editor,
// its Fluent menu, the pill row and the slot card together, against routes that answer in
// the backend's shapes (routes/prompt_programs.py `public`, /pools, /suggest, /add). Type a
// plain prompt, make a slot from an underline, choose in its builder, add light from the row
// under the text, leave it out, set the detail level, and generate.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/fluentStory.ts', import.meta.url)), name: 'FluentStoryTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

const YOUNG = ['18-year-old', '21-year-old', '24-year-old', '27-year-old']
const OLDER = ['35-year-old', '48-year-old', '62-year-old']
const HAIR = ['buzz cut', 'crew cut', 'side part', 'shoulder-length curls']
const LIGHTS = ['warm desk lamp glow', 'soft afternoon window light', 'cool overhead fluorescent light']

// A stand-in backend: the slot reader's result for the slots it knows, built into the
// editor's view of a program as `public()` builds it.
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
    if (words === 'young man') {
      const details = ['young_man.age', 'young_man.descent', 'young_man.hair']
      slots.push({ id: 'young_man', n, kind: 'person', label: 'Young man', words, span, line: 1, details, stated: { age: 'young' } })
      choices.push(
        { id: 'young_man.age', kind: 'pick', label: 'Age', cls: 'person.age_band', options: [...YOUNG, ...OLDER], slot: 'young_man', zones: [{ id: 'kinds', title: 'Young' }, { id: 'instead', title: 'Other ages' }] },
        { id: 'young_man.descent', kind: 'pick', label: 'Descent', cls: 'person.ethnicity', options: ['Korean', 'Irish', 'Nigerian'], slot: 'young_man' },
        { id: 'young_man.hair', kind: 'pick', label: 'Hair', cls: 'person.hairstyle', options: HAIR, slot: 'young_man' },
      )
    } else {
      const id = words.replace(/\W+/g, '_')
      slots.push({ id, n, kind: words === 'light' ? 'light' : 'free', label: words === 'light' ? 'Lighting' : words, words, span, line: 1, details: [id] })
      choices.push({ id, kind: 'pick', label: words === 'light' ? 'Lighting' : words, options: words === 'light' ? LIGHTS : [words], slot: id })
    }
  }
  return { key: slots.length ? `k:${slots.map(s => s.words).join('|')}` : null, slots, choices }
}

const pools = {
  'young_man.age': { options: [...YOUNG, ...OLDER], more: false, cls: 'person.age_band', label: 'Age', closed: true, zones: { kinds: YOUNG, instead: OLDER } },
  'young_man.descent': { options: ['Korean', 'Irish', 'Nigerian'], more: false, cls: 'person.ethnicity', label: 'Descent', closed: true },
  'young_man.hair': { options: HAIR, more: false, cls: 'person.hairstyle', label: 'Hairstyle', closed: true, groups: { length: { short: HAIR.slice(0, 3), long: HAIR.slice(3) } } },
  light: { options: LIGHTS, more: false, short: { [LIGHTS[0]]: 'desk lamp', [LIGHTS[1]]: 'window light', [LIGHTS[2]]: 'fluorescent' } },
}

async function open(t, { theme = 'dark', width = 900, height = 760, mobile = false, start = '', dev = false } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2, hasTouch: mobile, isMobile: mobile, colorScheme: theme })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const calls = { prepare: [], suggest: [], add: [], pools: [] }
  const prepared = new Set()
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
      if (body.cache_only && !prepared.has(read.key)) return json({ key: null })
      if (!body.cache_only) { await new Promise(r => setTimeout(r, 700)); prepared.add(read.key) }
      return json({ ...read, example: 'A dorm room with a 24-year-old Korean man', seconds: 0.7,
        ...(body.include_program ? { program: 'emit("dorm room with ")\nperson("young_man")', reading: { slots: [{ n: 1, kind: 'person', label: 'Young man' }] } } : {}) })
    }
    if (url.endsWith('/prompt-programs/pools')) {
      calls.pools.push(body)
      const read = readSlots(body.prompt)
      return json({ choices: Object.fromEntries(read.choices.map(c => [c.id, pools[c.id] || { options: c.options, more: false }])), more: [] })
    }
    if (url.endsWith('/prompt-programs/preview')) return json({ prompt: 'A dorm room with a 21-year-old Irish man with a buzz cut', draws: [{ id: 'young_man.age', value: '21-year-old' }] })
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
  const card = page.locator('[data-program-card]')
  const pills = page.locator('[data-program-choices]')
  return { page, calls, shot, card, pills, editor: page.locator('.cm-content') }
}

const text = page => page.evaluate(() => window.text())

async function story(t, opts = {}) {
  const tag = opts.tag || 'desktop-dark'
  const { page, calls, shot, card, pills, editor } = await open(t, opts)
  const tap = opts.mobile ? (l => l.tap()) : (l => l.click())

  // A plain prompt: Suggest underlines what could vary and offers what is absent.
  await editor.click()
  await page.keyboard.type('dorm room with a young man')
  await expect(page.locator('.cm-could-vary')).toHaveText('young man', { timeout: 4000 })
  await expect(page.locator('[data-slot-add]')).toHaveText(['light', 'camera'])
  assert.equal(calls.suggest.at(-1).prompt, 'dorm room with a young man')
  assert.equal(calls.suggest.at(-1).project_id, 7)
  // Nothing varies yet: no pills.
  await expect(pills).toHaveCount(0)
  await shot(`${tag}-1-underlined`)

  // Vary this wraps it and the card opens while the slot is read, then fills.
  await page.locator('.cm-could-vary').click()
  await tap(page.locator('[data-vary]'))
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
  await expect(card.locator('[data-writing]')).toContainText('Writing options')
  await shot(`${tag}-2-writing`)
  await expect(card.locator('[data-row="young_man.age"]')).toBeVisible({ timeout: 4000 })
  await expect(card.locator('[data-row="young_man.age"]')).toContainText('young')
  await shot(`${tag}-3-builder`)

  // Choose a hairstyle: it shows as a pill of its own.
  await tap(card.locator('[data-row="young_man.hair"]'))
  await tap(card.locator('[data-option="buzz cut"]'))
  await expect(pills.locator('[data-choice="young_man.hair"]')).toHaveText(/Hair\s*buzz cut/)
  await shot(`${tag}-4-chosen`)
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)
  await expect(pills.locator('[data-choice="young_man"]')).toHaveText('Young man')

  // + light writes it into the prompt as a slot and opens it.
  await tap(page.locator('[data-slot-add="light"]'))
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>, lit by <light>')
  assert.deepEqual(calls.add.at(-1), { project_id: 7, prompt: 'dorm room with a <young man>', name: 'light' })
  await expect(card.locator(`[data-option="${LIGHTS[0]}"]`)).toBeVisible({ timeout: 4000 })
  await expect(card.locator('[data-default]')).toHaveText('Any lighting')
  await expect(page.locator('[data-slot-add]')).toHaveText(['camera'], { timeout: 4000 })
  await shot(`${tag}-5-light`)

  // Leave it out.
  await tap(card.locator('[data-leave-out]'))
  await expect(card).toHaveCount(0)
  await expect(pills.locator('[data-choice="light"]')).toHaveText('No lighting')
  await shot(`${tag}-6-left-out`)

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
  assert.deepEqual(body.promptOptions.program, { enabled: true, choices: { 'young_man.hair': { values: ['buzz cut'] }, light: { off: true } } })
  assert.equal(body.promptOptions.autoImprove.enabled, true)
  assert.equal(body.promptOptions.autoImprove.level, 'expand')
  return { page, calls }
}

test('the main story, desktop dark', async t => { await story(t) })
test('the main story, desktop light', async t => { await story(t, { theme: 'light', tag: 'desktop-light' }) })
test('the main story, phone dark', async t => { await story(t, { width: 390, height: 844, mobile: true, tag: 'phone-dark' }) })
test('the main story, phone light', async t => { await story(t, { width: 390, height: 844, mobile: true, theme: 'light', tag: 'phone-light' }) })

test('the developer view shows the slot reading and the built program', async t => {
  const { page, card } = await open(t, { start: 'dorm room with a <young man>', dev: true })
  await expect(page.locator('[data-program-choices] [data-choice="young_man"]')).toBeVisible({ timeout: 4000 })
  await expect(card).toHaveCount(0)
  await page.locator('[data-fluent-chip]').click()
  await page.getByRole('button', { name: 'Show program' }).click()
  const dialog = page.locator('[data-program-debug]')
  await expect(dialog).toContainText('person("young_man")')
  await expect(dialog.locator('[data-reading]')).toContainText('"kind": "person"')
  await expect(dialog).toContainText('A dorm room with a 21-year-old Irish man')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/dev-dialog.png` })
})

test('the developer view of a prompt with nothing that varies says so', async t => {
  const { page } = await open(t, { start: 'a lighthouse at dusk', dev: true })
  await page.waitForTimeout(600)
  await page.locator('[data-fluent-chip]').click()
  await page.getByRole('button', { name: 'Show program' }).click()
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

// Touch: on a phone every pill, its ×, Reset and the + ideas are full-size targets (44px),
// the pills stay small to look at, four of them wrap, and no two targets overlap.
const FOUR = 'dorm room with a <young man> and his <pet>, lit by <light>, at a <late-night diner on the edge of town>'
const MIN = 44

async function measure(locator) {
  return locator.evaluateAll(els => els.map(el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } }))
}
const overlaps = (a, b) => a.x < b.x + b.w - 0.5 && b.x < a.x + a.w - 0.5 && a.y < b.y + b.h - 0.5 && b.y < a.y + a.h - 0.5

async function phonePills(t, theme) {
  const { page, card, pills, shot } = await open(t, { width: 390, height: 844, mobile: true, theme, start: FOUR })
  await expect(pills.locator('[data-choice]')).toHaveCount(4, { timeout: 4000 })
  // Choose a pet and leave out the light: two ×, and Reset.
  await pills.locator('[data-choice="pet"]').tap()
  await card.locator('[data-option="pet"]').tap()
  await expect(card.locator('[data-chosen] button[aria-label^="Remove"]')).toHaveCount(1)
  const chosen = await measure(card.locator('[data-chosen] button[aria-label^="Remove"]'))
  await shot(`phone-${theme}-chooser-chips`)
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)
  await pills.locator('[data-choice="light"]').tap()
  await card.locator('[data-leave-out]').tap()
  await expect(card).toHaveCount(0)
  await expect(pills.locator('[data-reset]')).toHaveCount(2)
  await expect(page.locator('[data-slot-add]')).toHaveText(['camera'], { timeout: 4000 })
  await shot(`phone-${theme}-pills`)
  return {
    page, pills, chosen,
    choice: await measure(pills.locator('[data-choice]')),
    reset: await measure(pills.locator('[data-reset]')),
    resetAll: await measure(pills.locator('[data-reset-all]')),
    adds: await measure(page.locator('[data-slot-add]')),
    visible: await measure(pills.locator('[data-choice]').locator('xpath=..')),
    row: (await measure(pills))[0],
  }
}

for (const theme of ['dark', 'light']) {
  test(`on a phone, pills, their ×, Reset and the + ideas are touch-sized, ${theme}`, async t => {
    const m = await phonePills(t, theme)
    if (process.env.PROMPT_MEASURE) console.log(JSON.stringify(m, (k, v) => typeof v === 'number' ? Math.round(v * 10) / 10 : v === m.page || v === m.pills ? undefined : v))
    const targets = { choice: m.choice, reset: m.reset, resetAll: m.resetAll, adds: m.adds, chosen: m.chosen }
    for (const [name, boxes] of Object.entries(targets)) {
      assert.ok(boxes.length, `${name} present`)
      for (const b of boxes) assert.ok(b.w >= MIN && b.h >= MIN, `${name} target ${b.w}x${b.h}`)
    }
    // Small to look at: no taller than the app's other chips.
    for (const v of m.visible) assert.ok(v.h <= 34, `visible pill ${v.h}px tall`)
    // Four pills (and Reset) wrap onto more than one line, all on screen.
    const rows = new Set(m.choice.map(b => Math.round(b.y)))
    assert.ok(rows.size >= 2, `pills on ${rows.size} line(s)`)
    const row = [...m.choice, ...m.reset, ...m.resetAll]
    for (const b of row) assert.ok(b.x >= m.row.x - 0.5 && b.x + b.w <= m.row.x + m.row.w + 0.5 && b.x >= 0 && b.x + b.w <= 390, `in the row: ${JSON.stringify(b)}`)
    // No target overlaps another: a tap lands on one thing. (A pill holds its own ×.)
    for (let i = 0; i < row.length; i++) for (let j = i + 1; j < row.length; j++) {
      const a = row[i], b = row[j]
      const nested = (p, q) => p.x <= q.x + 0.5 && p.y <= q.y + 0.5 && p.x + p.w >= q.x + q.w - 0.5 && p.y + p.h >= q.y + q.h - 0.5
      assert.ok(!overlaps(a, b) || nested(a, b) || nested(b, a), `targets overlap: ${JSON.stringify(a)} ${JSON.stringify(b)}`)
    }
    // A long value still truncates inside its pill.
    const truncated = await m.pills.locator('[data-choice] .truncate').evaluateAll(els => els.every(el => el.scrollWidth <= el.clientWidth + 1 || getComputedStyle(el).textOverflow === 'ellipsis'))
    assert.ok(truncated)
  })
}

test('on a desktop, pills keep their size', async t => {
  const { page, pills } = await open(t, { start: FOUR })
  await expect(pills.locator('[data-choice]')).toHaveCount(4, { timeout: 4000 })
  for (const b of await measure(pills.locator('[data-choice]'))) assert.ok(b.h <= 28, `desktop pill ${b.h}px`)
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
    for (const s of ['Vary this', 'press <', '+ light', 'Leave out', 'As written', 'Keep from this', 'Yours', 'Medium', 'High'])
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
