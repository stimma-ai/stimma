import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/loraNotes.ts', import.meta.url)), name: 'LoraNotesTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function open(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 420, height: 800 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app"></div></body></html>' }))
  await page.goto('http://lora-notes.test/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.locator('[data-lora-rows] > div.group').first().waitFor()
  const row = name => page.locator('[data-lora-rows] > div.group').filter({ hasText: name })
  return { page, row, errors }
}

test('a row without a fingerprint has no notes UI', async t => {
  const { page, row } = await open(t)
  await expect(row('plain').locator('[data-lora-note-button]')).toHaveCount(0)
  await expect(page.locator('[data-lora-note-button]')).toHaveCount(2)
})

test('rows that are on show their trigger words, and rows that are off do not', async t => {
  const { page, row } = await open(t)
  await expect(row('step-500').locator('[data-lora-trigger-line]')).toHaveText('clayrndr')
  await row('step-500').click()
  await expect(page.locator('[data-lora-trigger-line]')).toHaveCount(0)
})

test('working in the editor never toggles the row', async t => {
  const { page, row } = await open(t)
  const before = await row('step-500').getAttribute('class')
  await row('step-500').locator('[data-lora-note-button]').click()
  const editor = page.locator('[data-lora-note-editor]')
  await editor.locator('[data-lora-note-text]').click()
  await editor.locator('[data-lora-note-text]').fill('Clay look. Simple shapes.')
  await editor.locator('[data-lora-note-trigger]').fill('second word')
  await editor.locator('[data-lora-note-trigger]').press('Enter')
  assert.equal(await row('step-500').getAttribute('class'), before)
  await expect.poll(() => page.evaluate(() => window.calls.at(-1))).toEqual({
    save: 'series/clay_000000500.safetensors',
    trigger_words: ['clayrndr', 'second word'],
    notes: 'Clay look. Simple shapes.',
  })
})

test('sharing over other notes asks first, and Replace confirms', async t => {
  const { page, row } = await open(t)
  await row('step-500').locator('[data-lora-note-button]').click()
  await page.locator('[data-lora-note-series]').check()
  const conflict = page.locator('[data-lora-note-conflict]')
  await expect(conflict).toContainText('1 other file has a different note')
  await conflict.getByRole('button', { name: 'Replace' }).click()
  await expect.poll(() => page.evaluate(() => window.calls.at(-1))).toEqual({
    share: 'series/clay_000000500.safetensors',
    replace: true,
  })
  await expect(conflict).toHaveCount(0)
})

test('with Enhance off a missing trigger warns, and only Insert changes anything', async t => {
  const { page, row } = await open(t)
  await page.evaluate(() => window.setVerbatim('reading on a train'))
  const warning = row('step-500').locator('[data-lora-trigger-warning]')
  await expect(warning).toContainText("clayrndr isn't in your prompt")
  assert.deepEqual(await page.evaluate(() => window.inserted), [])
  await warning.getByRole('button', { name: 'Insert' }).click()
  assert.deepEqual(await page.evaluate(() => window.inserted), ['clayrndr'])
  await expect(row('step-500').locator('.opacity-50')).toHaveCount(0)

  await page.evaluate(() => window.setVerbatim('CLAYRNDR reading'))
  await expect(warning).toHaveCount(0)
  await expect(row('step-500').locator('[data-lora-trigger-line]')).toHaveText('clayrndr')
})
