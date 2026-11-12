import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The media info panel's prompt: the one the image was made from, with a switch
// to the prompt as typed (in the editor's syntax colors) only when they differ.
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

test('one prompt: no switch, the plain prompt as before', async t => {
  const { panel, shot } = await open(t, 'single')
  await expect(panel.getByRole('radiogroup')).toHaveCount(0)
  await expect(panel.locator('[data-testid="prompt-block"] p')).toHaveText(await panel.page().evaluate(() => window.MADE))
  await shot('single-desktop')
})

test('the same prompt twice: no switch', async t => {
  const { panel } = await open(t, 'identical')
  await expect(panel.getByRole('radiogroup')).toHaveCount(0)
  await expect(panel.locator('[data-testid="prompt-block"]')).toHaveCount(1)
  await expect(panel.getByText('As typed')).toHaveCount(0)
})

for (const [label, opts] of [
  ['desktop', {}],
  ['compact', { width: 390, viewport: { width: 390, height: 844 } }],
  ['desktop-light', { theme: 'light' }],
]) {
  test(`two prompts (${label}): the made-from prompt first, as typed one switch away`, async t => {
    const { page, panel, shot } = await open(t, 'pair', opts)
    const [made, typed] = await page.evaluate(() => [window.MADE, window.TYPED])
    const text = panel.locator('[data-testid="prompt-block"] p')
    const switcher = panel.getByRole('radiogroup', { name: 'Prompt version' })
    await expect(switcher.getByRole('radio', { name: 'Prompt' })).toHaveAttribute('aria-checked', 'true')
    await expect(text).toHaveText(made)
    await expect(text.locator('[data-syntax]')).toHaveCount(0)
    await expect(panel.getByText('Original prompt')).toHaveCount(0)
    await shot(`pair-made-${label}`)

    // The sections below move only by the text's own height.
    const factsTop = async () => (await panel.getByText('Seed').boundingBox()).y
    const textHeight = async () => (await text.boundingBox()).height
    const [top0, h0] = [await factsTop(), await textHeight()]

    await switcher.getByRole('radio', { name: 'As typed' }).click()
    await expect(switcher.getByRole('radio', { name: 'As typed' })).toHaveAttribute('aria-checked', 'true')
    await expect(text).toHaveText(typed)
    for (const kind of ['wildcard', 'named-wildcard', 'verbatim', 'comment']) {
      await expect(text.locator(`[data-syntax="${kind}"]`).first()).toBeVisible()
    }
    assert.deepEqual(await text.locator('[data-syntax="wildcard"]').allTextContents(), ['{yellow|red|navy}', '{rainy|foggy}', '{Lisbon|Porto}'])
    await expect(text.locator('[data-syntax="named-wildcard"]')).toHaveText('{{hairstyle}}')
    await expect(text.locator('[data-syntax="verbatim"]')).toHaveText('[ohwx woman]')
    await expect(text.locator('[data-syntax="comment"]')).toHaveText('# keep her face the same between images, vary the street')
    assert.ok(Math.abs((await factsTop() - top0) - (await textHeight() - h0)) < 1, 'only the prompt text changes height')
    await shot(`pair-typed-${label}`)

    // A click on the text copies the one shown.
    await text.click()
    await expect.poll(() => page.evaluate(() => window.copied.at(-1))).toBe(typed)
    await switcher.getByRole('radio', { name: 'Prompt' }).click()
    await text.click()
    await expect.poll(() => page.evaluate(() => window.copied.at(-1))).toBe(made)

    // Keyboard: the switch is reachable and flips with Space.
    await switcher.getByRole('radio', { name: 'As typed' }).focus()
    await page.keyboard.press('Space')
    await expect(text).toHaveText(typed)
  })
}

test('the editor marks the typed prompt as the read-only view does', async t => {
  const { page, panel } = await open(t, 'pair')
  await panel.getByRole('radio', { name: 'As typed' }).click()
  const view = {}
  for (const kind of ['wildcard', 'named-wildcard', 'verbatim', 'comment']) {
    view[kind] = await panel.locator(`[data-syntax="${kind}"]`).allTextContents()
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
