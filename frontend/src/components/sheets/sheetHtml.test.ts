import assert from 'node:assert/strict'
import test from 'node:test'

import { mediaIdOfRef, scopeCss } from './sheetHtml.ts'

test('agent CSS is nested under the sheet scope', () => {
  const css = scopeCss('.masthead h1 { color: var(--cs-accent); }', '[data-sheet-scope="s1"]')
  assert.ok(css.startsWith('[data-sheet-scope="s1"] {'))
  assert.ok(css.includes('.masthead h1'))
})

test('CSS that could escape its scope is dropped', () => {
  // A stray closing brace would end the scope and style the whole app.
  assert.equal(scopeCss('} body { display: none } .x {', '[data-sheet-scope="s1"]'), '')
  assert.equal(scopeCss('.a { color: red', '[data-sheet-scope="s1"]'), '')
  // Braces inside strings don't count.
  assert.ok(scopeCss('.a::after { content: "}" }', '[s]').includes('content'))
})

test('imports and external URLs never load', () => {
  const css = scopeCss('@import url(https://evil.example/x.css); .a { background: url(https://x.example/a.png) }', '[s]')
  assert.ok(!css.includes('@import'))
  assert.ok(!css.includes('https://'))
})

test('refs resolve to media ids', () => {
  assert.equal(mediaIdOfRef('media:12'), 12)
  assert.equal(mediaIdOfRef('12'), 12)
  assert.equal(mediaIdOfRef('asset:3'), null)
  assert.equal(mediaIdOfRef(''), null)
})
