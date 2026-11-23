import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The media info panel's prompt: one plain block when there's one version; when the
// image was made from a different prompt than the one typed, each version on a rail
// (You wrote, Filled in, Improved), the earlier ones a line each until opened.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/provenancePrompt.ts', import.meta.url)), name: 'ProvenancePromptTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)
const css = output.find(item => item.type === 'asset' && item.fileName.endsWith('.css'))
const SHOTS = process.env.PROMPT_SHOTS_DIR

async function open(t, name, { width = 384, viewport = { width: 900, height: 800 }, theme = 'dark' } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport, deviceScaleFactor: 2 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: `<html data-theme="${theme}"><body><div id="app"></div></body></html>` }))
  await page.goto('http://provenance-prompt.test/')
  if (css) await page.addStyleTag({ content: String(css.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.evaluate(([n, w]) => window.mountCase(n, w), [name, width])
  await page.locator('[data-panel]').waitFor()
  t.after(() => assert.deepEqual(errors, []))
  const shot = async file => { if (SHOTS) await page.locator('[data-panel]').screenshot({ path: `${SHOTS}/${file}.png` }) }
  return { page, panel: page.locator('[data-panel]'), shot }
}

test('one prompt: the plain prompt as before', async t => {
  const { panel, shot } = await open(t, 'single')
  await expect(panel.locator('[data-testid="prompt-stages"]')).toHaveCount(0)
  await expect(panel.locator('[data-testid="prompt-block"] p')).toHaveText(await panel.page().evaluate(() => window.MADE))
  await shot('single-desktop')
})

test('the same prompt twice: one block', async t => {
  const { panel } = await open(t, 'identical')
  await expect(panel.locator('[data-testid="prompt-stages"]')).toHaveCount(0)
  await expect(panel.locator('[data-testid="prompt-block"]')).toHaveCount(1)
  await expect(panel.getByText('You wrote')).toHaveCount(0)
})

const stage = (panel, key) => panel.locator(`[data-stage="${key}"]`)
const stageText = (panel, key) => stage(panel, key).locator('p')

for (const [label, opts] of [
  ['desktop', {}],
  ['compact', { width: 390, viewport: { width: 390, height: 844 } }],
  ['desktop-light', { theme: 'light' }],
]) {
  test(`typed and improved (${label}): the improved prompt whole, what was typed one line until opened`, async t => {
    const { page, panel, shot } = await open(t, 'pair', opts)
    const [made, typed] = await page.evaluate(() => [window.MADE, window.TYPED])
    await expect(stage(panel, 'filled')).toHaveCount(0)
    await expect(stage(panel, 'final')).toContainText('Improved')
    await expect(stageText(panel, 'final')).toHaveText(made)
    await expect(stageText(panel, 'typed')).toHaveText(typed)
    await expect(panel.getByText('Original prompt')).toHaveCount(0)

    // Closed: one line. The header opens it, in the editor's syntax colors.
    const typedLine = stageText(panel, 'typed')
    const lineHeight = async () => (await typedLine.boundingBox()).height
    assert.ok(await lineHeight() < 24, 'closed: a single line')
    await shot(`pair-closed-${label}`)
    const header = stage(panel, 'typed').getByRole('button', { name: 'You wrote' })
    await expect(header).toHaveAttribute('aria-expanded', 'false')
    await header.click()
    await expect(header).toHaveAttribute('aria-expanded', 'true')
    assert.ok(await lineHeight() > 40, 'open: the whole prompt')
    for (const kind of ['wildcard', 'named-wildcard', 'verbatim', 'comment']) {
      await expect(typedLine.locator(`[data-syntax="${kind}"]`).first()).toBeVisible()
    }
    assert.deepEqual(await typedLine.locator('[data-syntax="wildcard"]').allTextContents(), ['{yellow|red|navy}', '{rainy|foggy}', '{Lisbon|Porto}'])
    await expect(typedLine.locator('[data-syntax="named-wildcard"]')).toHaveText('{{hairstyle}}')
    await shot(`pair-open-${label}`)

    // A click on a stage's text copies that version.
    await typedLine.click()
    await expect.poll(() => page.evaluate(() => window.copied.at(-1))).toBe(typed)
    await stageText(panel, 'final').click()
    await expect.poll(() => page.evaluate(() => window.copied.at(-1))).toBe(made)

    // Keyboard: the header closes with Enter.
    await header.focus()
    await page.keyboard.press('Enter')
    await expect(header).toHaveAttribute('aria-expanded', 'false')
  })
}

test('Fluent: typed, filled in with its values marked, improved at its detail level', async t => {
  const { page, panel, shot } = await open(t, 'fluent')
  const fluent = await page.evaluate(() => window.FLUENT)
  assert.deepEqual(await panel.locator('[data-stage]').evaluateAll(els => els.map(el => el.dataset.stage)), ['typed', 'filled', 'final'])
  await expect(stage(panel, 'final')).toContainText('Improved · High detail')
  await expect(stageText(panel, 'final')).toHaveText(fluent.improved)
  await expect(stageText(panel, 'typed').locator('[data-syntax="slot"]')).toHaveText(['<glasses>', '<a sunlit loft>'])
  const filled = stageText(panel, 'filled')
  await expect(filled).toHaveText(fluent.filled)
  await expect(filled.locator('[data-syntax="slot"]')).toHaveText(['thin-rimmed glasses', 'a converted brick loft at golden hour'])
  await expect(filled.locator('[data-syntax="wildcard"]')).toHaveText('window seat')
  await expect(filled.locator('[data-syntax="slot"]').first()).toHaveAttribute('title', '<glasses>')
  await shot('fluent-closed')
  await stage(panel, 'filled').getByRole('button', { name: 'Filled in' }).click()
  await stage(panel, 'typed').getByRole('button', { name: 'You wrote' }).click()
  await shot('fluent-open')
  await stage(panel, 'filled').hover()
  await stage(panel, 'filled').getByRole('button', { name: 'Copy' }).click()
  await expect.poll(() => page.evaluate(() => window.copied.at(-1))).toBe(fluent.filled)
})

test('nothing filled in (the prompt as typed): typed, then improved at its level', async t => {
  const { panel } = await open(t, 'plainFluent')
  assert.deepEqual(await panel.locator('[data-stage]').evaluateAll(els => els.map(el => el.dataset.stage)), ['typed', 'final'])
  await expect(stage(panel, 'final')).toContainText('Improved · High detail')
})

test('filled in but not improved: the filled prompt is the last stage', async t => {
  const { page, panel } = await open(t, 'filledOnly')
  const fluent = await page.evaluate(() => window.FLUENT)
  assert.deepEqual(await panel.locator('[data-stage]').evaluateAll(els => els.map(el => el.dataset.stage)), ['typed', 'final'])
  await expect(stage(panel, 'final')).toContainText('Filled in')
  await expect(stage(panel, 'final')).not.toContainText('Improved')
  await expect(stageText(panel, 'final')).toHaveText(fluent.filled)
  await expect(stageText(panel, 'final').locator('[data-syntax="wildcard"]')).toHaveText('window seat')
})

test('the editor marks the typed prompt as the read-only view does', async t => {
  const { page, panel } = await open(t, 'pair')
  await panel.getByRole('button', { name: 'You wrote' }).click()
  const view = {}
  for (const kind of ['wildcard', 'named-wildcard', 'verbatim', 'comment']) {
    view[kind] = await stageText(panel, 'typed').locator(`[data-syntax="${kind}"]`).allTextContents()
  }
  await page.evaluate(() => window.mountEditor(window.TYPED, 'enhance', ['hairstyle']))
  const editor = page.locator('[data-editor] .cm-content')
  await editor.waitFor()
  const marks = cls => editor.locator(`.${cls}`).allTextContents()
  assert.deepEqual({
    'wildcard': await marks('cm-wildcard'),
    'named-wildcard': await marks('cm-named-wildcard'),
    'verbatim': await marks('cm-verbatim'),
    'comment': await marks('cm-comment-line'),
  }, view)

  // A name nothing can fill is flagged; raw marks nothing.
  await page.evaluate(() => window.mountEditor('{{hairstyle}} {{outfit}} {a|b}\n# note', 'plain', ['hairstyle']))
  await expect(page.locator('[data-editor] .cm-named-wildcard')).toHaveText('{{hairstyle}}')
  await expect(page.locator('[data-editor] .cm-unknown-name')).toHaveText('{{outfit}}')
  await expect(page.locator('[data-editor] .cm-comment-line')).toHaveAttribute('title', /No chat model/)
  await page.evaluate(() => window.mountEditor('{{hairstyle}} {a|b} [x]', 'raw'))
  await expect(page.locator('[data-editor] .cm-content')).toHaveText('{{hairstyle}} {a|b} [x]')
  await expect(page.locator('[data-editor] [class*="cm-wildcard"], [data-editor] .cm-named-wildcard, [data-editor] .cm-verbatim')).toHaveCount(0)
})
