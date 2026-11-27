import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// The prompt box with Vim keybindings on: Ctrl+A, Ctrl+C and Ctrl+V select all, copy and paste
// as they do with Vim off, not Vim's increment and block-visual. Ctrl+C with nothing selected is
// still Vim's Escape, and after a copy Vim is back in normal mode. The real AIPromptEditor, from
// the prompt slots fixture.
const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: fileURLToPath(new URL('./fixtures/promptSlots.ts', import.meta.url)), name: 'PromptVimClipboardTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const PROMPT = 'red dress on a beach'

async function open(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    if (route.request().url().includes('/api/') || route.request().url().includes('/prompt-programs/')) {
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    }
    return route.fulfill({ contentType: 'text/html', body: `<html><body><script>localStorage.setItem('stimma:vim-mode', 'true'); window.START = ${JSON.stringify(PROMPT)}</script><div id="app"></div></body></html>` })
  })
  await page.goto('http://localhost/')
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  const editor = page.locator('.cm-content')
  await editor.waitFor()
  t.after(() => assert.deepEqual(errors, []))
  await editor.click()
  await page.keyboard.press('Escape')
  return { page, editor }
}

const clipboard = page => page.evaluate(() => navigator.clipboard.readText())
const setClipboard = (page, text) => page.evaluate(t => navigator.clipboard.writeText(t), text)
const text = page => page.evaluate(() => window.text())

// On macOS Cmd selects, copies and pastes, and Ctrl+A, Ctrl+C and Ctrl+V stay Vim's.
const ctrlKeys = { skip: process.platform === 'darwin' && 'Ctrl+A, Ctrl+C and Ctrl+V are Vim\'s on macOS' }

test('in Vim normal mode, Ctrl+A then Ctrl+C copies the prompt', ctrlKeys, async t => {
  const { page } = await open(t)
  await setClipboard(page, 'before')
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Control+c')
  await expect.poll(() => clipboard(page)).toBe(PROMPT)
  // Back in normal mode: x deletes one character, not the selection.
  await page.keyboard.type('x')
  await expect.poll(() => text(page)).toBe(PROMPT.slice(0, -1))
})

test('in Vim normal mode, Ctrl+A then Ctrl+V replaces the prompt', ctrlKeys, async t => {
  const { page } = await open(t)
  await setClipboard(page, 'a lighthouse')
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Control+v')
  await expect.poll(() => text(page)).toBe('a lighthouse')
})

test('in Vim normal mode, Ctrl+V pastes', ctrlKeys, async t => {
  const { page } = await open(t)
  await page.keyboard.type('$')
  await setClipboard(page, ' at dusk')
  await page.keyboard.press('Control+v')
  await expect.poll(() => text(page)).toBe(`${PROMPT} at dusk`)
})

test('Ctrl+C with nothing selected is still Vim\'s Escape', async t => {
  const { page } = await open(t)
  await page.keyboard.type('A')
  await page.keyboard.press('Control+c')
  await page.keyboard.type('x')
  await expect.poll(() => text(page)).toBe(PROMPT.slice(0, -1))
})
