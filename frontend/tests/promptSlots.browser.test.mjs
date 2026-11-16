import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Making and opening slots in the prompt editor (Fluent): underlined phrases and the Add Detail /
// Add Variety offer, `<` around a selection, the suggestions under the text (phrase chips and + chips
// that write a slot in), and the open-slot event.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/promptSlots.ts', import.meta.url)), name: 'PromptSlotsTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

const PROMPT = 'dorm room with a young man'
// What the editor asks the kind of, by the words selected; '' when it can't be said.
const KINDS = { porch: 'place', cat: '' }

/** Where words go at the end of the last picture line (not a # note), as suggest.py places the camera. */
function endOfPicture(prompt) {
  let at = 0
  let best = null
  for (const line of prompt.split('\n')) {
    if (line.trim() && !line.trim().startsWith('#')) best = at + line.trimEnd().length
    at += line.length + 1
  }
  return best
}

/** /suggest as the backend answers: "young man" while it isn't a slot (Suggest's way and mode
    as asked), a face after him (a slot or not) and a camera at the end, each while its slot
    isn't in the prompt. `reverse` gives the adds the other way round. */
function answer(prompt, { way = 'detail', mode = 'kind', reverse = false } = {}) {
  const inNote = at => prompt.slice(prompt.lastIndexOf('\n', at) + 1).trimStart().startsWith('#')
  let i = prompt.indexOf('young man')
  while (i >= 0 && inNote(i)) i = prompt.indexOf('young man', i + 1)
  const phrases = i >= 0 && prompt[i - 1] !== '<' ? [{ from: i, to: i + 9, text: 'young man', kind: 'person', way, mode, label: 'man' }] : []
  const adds = []
  if (i >= 0 && !prompt.includes('<face>')) adds.push({ key: 'face', label: 'Face', at: i + 9 + (prompt[i - 1] === '<' ? 1 : 0), text: ' with <face>' })
  const end = endOfPicture(prompt)
  if (end != null && !prompt.includes('<camera>')) adds.push({ key: 'camera', label: 'Camera', at: end, text: ', <camera>' })
  return { phrases, adds: reverse ? adds.reverse() : adds }
}

async function open(t, { start = PROMPT, theme = 'dark', suggest = {}, delay = 0 } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 900, height: 700 }, deviceScaleFactor: 2 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const calls = { suggest: [], kind: [] }
  await page.route('**/*', async route => {
    const url = route.request().url()
    if (url.endsWith('/prompt-programs/suggest')) {
      const body = route.request().postDataJSON()
      calls.suggest.push(body)
      const how = typeof suggest === 'function' ? suggest(calls.suggest.length) : suggest
      if (delay) await new Promise(resolve => setTimeout(resolve, delay))
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(answer(body.prompt, how)) })
    }
    if (url.endsWith('/prompt-programs/suggest-kind')) {
      const body = route.request().postDataJSON()
      calls.kind.push(body)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ kind: KINDS[body.prompt.slice(body.start, body.end)] ?? '' }) })
    }
    if (url.includes('/api/')) return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    return route.fulfill({ contentType: 'text/html', body: `<html data-theme="${theme}"><body><script>window.START = ${JSON.stringify(start)}</script><div id="app"></div></body></html>` })
  })
  await page.goto('http://prompt-slots.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  const editor = page.locator('.cm-content')
  await editor.waitFor()
  t.after(() => assert.deepEqual(errors, []))
  const shot = async file => { if (SHOTS) await page.locator('#app').screenshot({ path: `${SHOTS}/${file}.png` }) }
  return { page, editor, calls, shot }
}

const text = page => page.evaluate(() => window.text())
const opened = page => page.evaluate(() => window.opened)
const modes = page => page.evaluate(() => window.modes)
const offered = page => page.locator('[data-slot-offer] [data-way]')
const chips = page => page.locator('[data-slot-adds] button')
/** Select the last `n` characters of the first line. */
async function selectEnd(page, editor, n) {
  await editor.click()
  await page.keyboard.press('End')
  for (let i = 0; i < n; i++) await page.keyboard.press('Shift+ArrowLeft')
}

test('a phrase Fluent underlines becomes a slot with Add Detail, and opens', async t => {
  const { page, editor, calls, shot } = await open(t)
  await expect(page.locator('.cm-could-vary')).toHaveText('young man', { timeout: 3000 })
  assert.deepEqual(calls.suggest, [{ project_id: 7, prompt: PROMPT, previous: { phrases: [], adds: [] } }])
  await expect(page.locator('[data-slot-vary]')).toHaveText(['Add Detail: man'])
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'])
  await shot('underlined')

  await page.locator('.cm-could-vary').click()
  await expect(offered(page)).toHaveText(['Add Detail', 'Add Variety'])
  assert.deepEqual(calls.kind, [], 'Suggest named its kind: nothing asked')
  await shot('vary-offer')
  await page.locator('[data-slot-offer] [data-way="detail"]').click()
  await expect.poll(() => text(page)).toBe('dorm room with a <young man>')
  assert.deepEqual(await modes(page), [], 'Add Detail on a kind is how a slot starts')
  await expect(editor.locator('.cm-slot')).toHaveText('<young man>')
  await expect(offered(page)).toHaveCount(0)
  const [o] = await opened(page)
  assert.equal(o.n, 1)
  assert.equal(o.words, 'young man')
  assert.ok(o.rect.width > 20 && o.rect.height > 10, 'the slot\'s place on screen')

  // Clicking the slot opens it again.
  await editor.locator('.cm-slot').click()
  await expect.poll(async () => (await opened(page)).length).toBe(2)
  assert.deepEqual((await opened(page))[1].words, 'young man')
})

test('every underline offers both, Suggest\'s way first; Add Detail keeps the words, Add Variety writes the kind', async t => {
  for (const [way, mode, order, pick, after, said] of [
    ['detail', 'kind', ['detail', 'any'], 'detail', 'dorm room with a <young man>', []],
    ['detail', 'one', ['detail', 'any'], 'detail', 'dorm room with a <young man>', []],
    ['any', 'kind', ['any', 'detail'], 'any', 'dorm room with a <person>', []],
    ['any', 'one', ['any', 'detail'], 'detail', 'dorm room with a <young man>', []],
    ['detail', 'one', ['detail', 'any'], 'any', 'dorm room with a <person>', []],
  ]) {
    const { page, shot } = await open(t, { suggest: { way, mode } })
    await page.locator('.cm-could-vary').click()
    await expect(offered(page)).toHaveCount(2)
    assert.deepEqual(await offered(page).evaluateAll(b => b.map(e => e.dataset.way)), order, `${way}/${mode}`)
    // Two words each, never the prompt's words or the kind.
    await expect(offered(page)).toHaveText(order.map(w => (w === 'any' ? 'Add Variety' : 'Add Detail')))
    if (way === 'any' && mode === 'kind') await shot('any-offer')
    await page.locator(`[data-slot-offer] [data-way="${pick}"]`).click()
    await expect.poll(() => text(page)).toBe(after)
    await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, after.match(/<(.+)>/)[1]]])
    // Suggest's reading never becomes the user's mode: the reader decides.
    assert.deepEqual(await modes(page), said, `${way}/${mode} → ${pick}`)
    await expect(offered(page)).toHaveCount(0)
  }
})

test('the offer by keyboard: Tab into it, arrows between, Enter picks, Escape goes back', async t => {
  const { page, editor, calls } = await open(t, { start: 'a cat on a porch' })
  await selectEnd(page, editor, 5)
  // Words Suggest didn't name: Add Variety waits for their kind.
  await expect(offered(page)).toHaveText(['Add Detail', 'Add Variety'])
  await expect(page.locator('[data-slot-offer] [data-way="any"]')).toBeEnabled()
  assert.deepEqual(calls.kind.at(-1), { project_id: 7, prompt: 'a cat on a porch', start: 11, end: 16 })
  await page.keyboard.press('Tab')
  await expect(page.locator('[data-slot-offer] [data-way="detail"]')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(offered(page)).toHaveCount(0)
  await expect(editor).toBeFocused()
  assert.equal(await text(page), 'a cat on a porch')

  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  await expect(offered(page)).toHaveCount(2)
  await page.keyboard.press('Tab')
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-slot-offer] [data-way="any"]')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect.poll(() => text(page)).toBe('a cat on a <place>')
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'place']])
  assert.deepEqual(await modes(page), [])
  await expect(editor).toBeFocused()
})

test('Add Variety is off while the words have no kind', async t => {
  const { page, editor, calls } = await open(t, { start: 'a cat on a porch' })
  await editor.click()
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  for (let i = 0; i < 3; i++) await page.keyboard.press('Shift+ArrowRight')
  await expect(offered(page)).toHaveText(['Add Detail', 'Add Variety'])
  await expect.poll(() => calls.kind.map(c => c.prompt.slice(c.start, c.end))).toContain('cat')
  await page.waitForTimeout(200)
  await expect(page.locator('[data-slot-offer] [data-way="any"]')).toBeDisabled()
  await page.locator('[data-slot-offer] [data-way="detail"]').click()
  await expect.poll(() => text(page)).toBe('a <cat> on a porch')
})

test('selected words: Add Detail under them, and < wraps them; with nothing selected < types', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a porch' })
  await selectEnd(page, editor, 5)
  await expect(page.locator('[data-slot-offer] [data-way="detail"]')).toBeVisible()
  await page.keyboard.type('<')
  await expect.poll(() => text(page)).toBe('a cat on a <porch>')
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'porch']])

  // Undo takes the brackets off in one step.
  await page.keyboard.press('Control+z')
  await expect.poll(() => text(page)).toBe('a cat on a porch')

  await page.keyboard.press('End')
  await page.keyboard.type(' <')
  await expect.poll(() => text(page)).toBe('a cat on a porch <')
})

/** Where `word` is on screen (its first match in the text): left, right, middle y. */
const wordAt = (page, word) => page.evaluate(w => {
  const walker = document.createTreeWalker(document.querySelector('.cm-content'), NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const i = n.data.indexOf(w)
    if (i < 0) continue
    const r = document.createRange()
    r.setStart(n, i)
    r.setEnd(n, i + w.length)
    const b = r.getBoundingClientRect()
    return { left: b.left, right: b.right, y: b.top + b.height / 2 }
  }
  return null
}, word)

async function drag(page, from, to) {
  await page.mouse.move(from.x, from.y)
  await page.mouse.down()
  await page.mouse.move(to.x, to.y, { steps: 8 })
  await page.mouse.up()
}

test('every way of selecting words offers Add Detail; a collapsed selection hides it', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a sunny porch' })
  const offer = page.locator('[data-slot-offer]')
  const detailOn = async (how, wrapped) => {
    await expect(offer, how).toBeVisible()
    await page.locator('[data-slot-offer] [data-way="detail"]').click()
    await expect.poll(() => text(page), how).toBe(wrapped)
    await page.keyboard.press('Control+z')
    await expect.poll(() => text(page)).toBe('a cat on a sunny porch')
    await page.keyboard.press('Escape')
  }
  const collapse = async how => {
    const porch = await wordAt(page, 'porch')
    await page.mouse.click(porch.right - 2, porch.y)
    await expect(offer, how).toHaveCount(0)
  }

  // A drag released below the text, in the empty part of the box: the release lands outside
  // the text, and once missed it used to silence every later selection too.
  const sunny = await wordAt(page, 'sunny')
  const box = await editor.boundingBox()
  await editor.click()
  await drag(page, { x: sunny.left + 1, y: sunny.y }, { x: box.x + box.width - 4, y: box.y + box.height + 30 })
  await expect(offer, 'drag released below the editor').toBeVisible()
  await collapse('a click collapses it')

  // Then the keyboard: Shift+arrows, after that missed release.
  await page.keyboard.press('End')
  for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+ArrowLeft')
  await detailOn('shift+arrows', 'a cat on a sunny <porch>')
  await collapse('collapsed after the keyboard')

  // Right to left, starting and ending mid-word: the offer takes the whole words.
  const cat = await wordAt(page, 'cat')
  const sunny2 = await wordAt(page, 'sunny')
  await drag(page, { x: sunny2.left + 12, y: sunny2.y }, { x: cat.left + 8, y: cat.y })
  await detailOn('right-to-left drag, mid-word', 'a <cat on a sunny> porch')
  await collapse('collapsed after the drag')

  // A double-click on a word.
  await page.mouse.dblclick(sunny2.left + 6, sunny2.y)
  await detailOn('double-click', 'a cat on a <sunny> porch')

  // Select all, with the editor not focused before.
  await page.locator('#app').click({ position: { x: 2, y: 2 } })
  await editor.click()
  await page.keyboard.press('Control+a')
  await expect(offer, 'select all').toBeVisible()
  await page.keyboard.press('ArrowRight')
  await expect(offer, 'an arrow collapses it').toHaveCount(0)

  // A selection with no mouse at all, as touch handles make: the page's own selection.
  await page.evaluate(() => {
    const line = document.querySelector('.cm-line')
    const node = [...line.childNodes].find(n => n.nodeType === 3 && n.data.includes('cat')) ?? line.firstChild
    const i = node.data.indexOf('cat')
    getSelection().setBaseAndExtent(node, i, node, i + 3)
  })
  await detailOn('a selection without the mouse', 'a <cat> on a sunny porch')
})

test('on touch, the offer floats by the words and is not turned into a bottom sheet', async t => {
  const { page, editor } = await open(t, { start: 'a cat on a porch' })
  // Touch converts every fixed menu-tier box into a sheet with a full-screen backdrop,
  // which would cover the text and take the taps and drags that adjust the selection.
  await page.evaluate(() => document.documentElement.setAttribute('data-pointer', 'coarse'))
  await selectEnd(page, editor, 5)
  const chip = page.locator('[data-slot-offer]')
  await expect(chip).toBeVisible()
  const words = await editor.boundingBox()
  await expect(offered(page)).toHaveText(['Add Detail', 'Add Variety'])
  const box = await chip.boundingBox()
  assert.ok(box.width < 320, `chip width ${box.width}: not a full-width sheet`)
  for (const b of await offered(page).all()) assert.ok((await b.boundingBox()).height >= 43, 'a touch-sized target')
  assert.ok(box.y < words.y + words.height + 60, `chip at ${box.y}: beside the words, not at the bottom`)
  assert.equal(await page.locator('[data-sheet-backdrop]').count(), 0)
})

test('no wrapping in a comment line or inside a list', async t => {
  const { page, editor } = await open(t, { start: '# a young man\na {red|blue} coat' })
  await editor.click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.press('End')
  for (let i = 0; i < 3; i++) await page.keyboard.press('Shift+ArrowLeft')
  await page.waitForTimeout(250)
  await expect(offered(page)).toHaveCount(0)
  await page.keyboard.type('<')
  await expect.poll(() => text(page)).toBe('# a young <\na {red|blue} coat')
  assert.deepEqual(await opened(page), [])
})

test('a phrase chip takes its words Suggest\'s way and opens the slot, as the offer does', async t => {
  for (const [how, label, after] of [
    [{ way: 'detail', mode: 'one' }, 'Add Detail: man', 'dorm room with a <young man>'],
    [{ way: 'any' }, 'Add Variety: man', 'dorm room with a <person>'],
  ]) {
    const { page } = await open(t, { suggest: how })
    const chip = page.locator('[data-slot-vary="young man"]')
    await expect(chip).toHaveText(label)
    await expect(chip).toHaveAttribute('data-way', how.way)
    await chip.click()
    await expect.poll(() => text(page)).toBe(after)
    await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, after.match(/<(.+)>/)[1]]])
    assert.deepEqual(await modes(page), [], 'no mode stored from Suggest')
    await expect(page.locator('[data-slot-vary]')).toHaveCount(0)
  }
})

test('an add writes its slot where Suggest placed it, opens it, and undoes in one step', async t => {
  const { page, calls, shot } = await open(t)
  await page.locator('[data-slot-add="camera"]').click()
  await expect.poll(() => text(page)).toBe(`${PROMPT}, <camera>`)
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'camera']])
  // Its slot is in the prompt now: its chip goes; the others stay where they were.
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face'])
  await expect(page.locator('[data-slot-vary]')).toHaveText(['Add Detail: man'])
  await shot('added')
  // Once Suggest has answered for the text with the camera in it.
  await expect.poll(() => calls.suggest.map(c => c.prompt), { timeout: 4000 }).toContain(`${PROMPT}, <camera>`)
  await page.waitForTimeout(100)
  await page.locator('[data-slot-add="face"]').click()
  await expect.poll(() => text(page)).toBe('dorm room with a young man with <face>, <camera>')
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[1, 'camera'], [1, 'face']])
  await expect(page.locator('[data-slot-add]')).toHaveCount(0)
  await page.locator('.cm-content').click()
  await page.keyboard.press('Control+z')
  await expect.poll(() => text(page)).toBe(`${PROMPT}, <camera>`)
  await page.keyboard.press('Control+z')
  await expect.poll(() => text(page)).toBe(PROMPT)
})

test('a face goes after a person who is a slot', async t => {
  const { page } = await open(t, { start: 'dorm room with a <young man>' })
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'], { timeout: 3000 })
  await page.locator('[data-slot-add="face"]').click()
  await expect.poll(() => text(page)).toBe('dorm room with a <young man> with <face>')
  await expect.poll(async () => (await opened(page)).map(o => [o.n, o.words])).toEqual([[2, 'face']])
})

test('chips move with the edits, Suggest is told what shows, and a fresh answer keeps their order', async t => {
  const { page, editor, calls } = await open(t, { suggest: n => ({ reverse: n > 1 }) })
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'], { timeout: 3000 })
  await editor.click()
  await page.keyboard.press('End')
  await page.keyboard.type(' asleep')
  // Between answers the chips stay, moved with the text.
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'])
  await expect.poll(() => calls.suggest.length, { timeout: 4000 }).toBe(2)
  assert.deepEqual(calls.suggest[1], { project_id: 7, prompt: `${PROMPT} asleep`,
    previous: { phrases: [{ text: 'young man', way: 'detail', kind: 'person', mode: 'kind', label: 'man' }], adds: ['face', 'camera'] } })
  await page.waitForTimeout(300)
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'])
  await page.locator('[data-slot-add="camera"]').click()
  await expect.poll(() => text(page)).toBe(`${PROMPT} asleep, <camera>`)
})

test('a placeholder shows while an answer comes', async t => {
  const { page } = await open(t, { delay: 800 })
  await expect(page.locator('[data-suggest-loading]')).toHaveCount(1)
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'], { timeout: 4000 })
  await expect(page.locator('[data-suggest-loading]')).toHaveCount(0)
})

test('an add fits while its place is outside every slot and no slot has its words', async t => {
  const { page } = await open(t, { start: '' })
  const keys = (text, adds) => page.evaluate(([t, a]) => window.usableAdds(t, a).map(x => x.key), [text, adds])
  const add = (key, at) => ({ key, label: key, at, text: `, <${key}>` })
  assert.deepEqual(await keys('a farmer', [add('face', 8), add('camera', 8)]), ['face', 'camera'])
  assert.deepEqual(await keys('a farmer, <camera>', [add('face', 8), add('camera', 18)]), ['face'])
  assert.deepEqual(await keys('a farmer, < Camera >', [add('camera', 8)]), ['camera'], 'not a slot: spaces inside')
  assert.deepEqual(await keys('a farmer, <Camera>', [add('camera', 8)]), [])
  assert.deepEqual(await keys('a <farmer> here', [add('a', 3), add('b', 9), add('c', 10), add('d', 2)]), ['c', 'd'])
  assert.deepEqual(await keys('a cat', [add('a', -1), add('b', 6), add('c', 5), add('d', 0)]), ['c', 'd'])
})


test('Raw and Direct: no suggestions, slots don\'t open; names are marked in every mode', async t => {
  const { page, editor, calls } = await open(t, { start: '' })
  await page.waitForTimeout(1200)
  assert.equal(calls.suggest.length, 0, 'nothing asked for an empty prompt')

  await page.evaluate(() => window.setWay('direct'))
  await page.evaluate(() => window.setText('a <young man> with {{hairstyle}} in {{outfit}}'))
  await expect(editor.locator('.cm-named-wildcard')).toHaveText('{{hairstyle}}')
  await expect(editor.locator('.cm-unknown-name')).toHaveText('{{outfit}}')
  await expect(editor.locator('.cm-slot')).toHaveText('<young man>')
  await editor.locator('.cm-slot').click()
  await page.waitForTimeout(1200)
  assert.equal(calls.suggest.length, 0)
  assert.deepEqual(await opened(page), [])
  await expect(page.locator('[data-slot-adds]')).toHaveCount(0)

  await page.evaluate(() => window.setWay('raw'))
  await expect(editor.locator('.cm-slot, .cm-unknown-name')).toHaveCount(0)
  await page.waitForTimeout(1200)
  assert.equal(calls.suggest.length, 0)
})

test('light theme', async t => {
  const { page, shot } = await open(t, { start: 'a <young man> in a {red|blue} coat with {{hairstyle}}, [ohwx], {{outfit}}\n# a note', theme: 'light' })
  await expect(page.locator('[data-slot-add]')).toHaveText(['Face', 'Camera'], { timeout: 3000 })
  await shot('light')
})
