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
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/modalFocus.ts', import.meta.url)), name: 'ModalFocusTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.route('http://modal-focus.test/**', route => route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }))
  await page.goto('http://modal-focus.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  return page
}

test('Modal cycles Tab and Shift+Tab, skips unavailable controls, and returns focus', async t => {
  const page = await fixture(t)
  const opener = page.getByRole('button', { name: 'Open dialog', exact: true })
  await opener.click()
  await expect(page.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'First', exact: true })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('button', { name: 'Last', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'First', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('textbox', { name: 'Dialog field' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Open nested' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(opener).toBeFocused()
})

test('only the topmost Modal traps focus, including an empty nested dialog', async t => {
  const page = await fixture(t)
  await page.getByRole('button', { name: 'Open dialog', exact: true }).click()
  const nestedOpener = page.getByRole('button', { name: 'Open nested' })
  await nestedOpener.click()
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('button', { name: 'Nested last' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Nested first' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(nestedOpener).toBeFocused()
  await page.evaluate(() => window.modalFocus.empty())
  const emptyDialog = page.getByRole('dialog').last()
  await expect(emptyDialog).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(emptyDialog).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(emptyDialog).toBeFocused()
})

test('Modal suppresses grid shortcuts while CodeMirror retains editing keys', async t => {
  const page = await fixture(t)
  await page.getByRole('button', { name: 'Outside', exact: true }).focus()
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Delete')
  assert.deepEqual(await page.evaluate(() => window.modalFocus.shortcuts), ['a', 'Delete'])
  await page.evaluate(() => { window.modalFocus.shortcuts.length = 0 })
  await page.getByRole('button', { name: 'Open dialog', exact: true }).click()
  await page.getByRole('button', { name: 'First', exact: true }).focus()
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Meta+a')
  await page.keyboard.press('Delete')
  assert.deepEqual(await page.evaluate(() => window.modalFocus.shortcuts), [])
  const editor = page.locator('.cm-content')
  await editor.focus()
  await page.keyboard.press('Home')
  await page.keyboard.press('Tab')
  await expect(editor).toBeFocused()
  assert.match(await page.evaluate(() => window.modalFocus.editorText()), /^\s+text$/)
  await page.keyboard.type('added')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeVisible()
  assert.deepEqual(await page.evaluate(() => window.modalFocus.shortcuts), [])
  await page.getByRole('button', { name: 'Last', exact: true }).focus()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.keyboard.press('Delete')
  assert.deepEqual(await page.evaluate(() => window.modalFocus.shortcuts), ['Delete'])
})

test('Tooltip names unnamed icon buttons and preserves existing names', async t => {
  const page = await fixture(t)
  await expect(page.locator('[data-icon]')).toHaveAccessibleName('Remove item')
  await expect(page.getByRole('button', { name: 'Explicit name' })).toHaveAccessibleName('Explicit name')
  await expect(page.getByRole('button', { name: 'Visible name' })).toHaveAccessibleName('Visible name')
  await page.evaluate(() => window.modalFocus.rename())
  await expect(page.locator('[data-icon]')).toHaveAccessibleName('Delete item')
})
