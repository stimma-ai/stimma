import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { findSlots, lineSyntaxRanges, promptSyntaxSpans } from './promptSyntax.ts'
import { processFinalPrompt, unwrapSlots } from './promptProcessor.ts'

// Shared with backend/tests/test_slots_grammar.py: both sides must find the same slots.
const SLOT_CASES: { text: string; slots: [number, number][] }[] = JSON.parse(
  readFileSync(new URL('./slotGrammar.cases.json', import.meta.url), 'utf-8'),
)

const marked = (line: string, opts = {}) => lineSyntaxRanges(line, opts).map(r => [r.kind, line.slice(r.from, r.to)])

test('a line marks lists, wildcards and verbatim text, in order', () => {
  assert.deepEqual(marked('a {red|blue} coat, {{hairstyle}}, [ohwx woman]'), [
    ['wildcard', '{red|blue}'],
    ['named-wildcard', '{{hairstyle}}'],
    ['verbatim', '[ohwx woman]'],
  ])
})

test('braces without a pipe are plain text; nested lists are one list', () => {
  assert.deepEqual(marked('{just braces} and {a|{b|c}}'), [['wildcard', '{a|{b|c}}']])
})

test('a # line is a comment whole, whatever it holds', () => {
  assert.deepEqual(marked('  # vary {a|b} and [x]'), [['comment', '  # vary {a|b} and [x]']])
  assert.deepEqual(marked('# note', { mode: 'plain' }), [['comment-unread', '# note']])
})

test('a {{name}} nothing fills is marked in every mode; raw marks nothing', () => {
  const known = new Set(['hairstyle'])
  for (const mode of ['plain', 'enhance'] as const) {
    assert.deepEqual(marked('{{Hairstyle}} {{outfit}}', { mode, known }), [
      ['named-wildcard', '{{Hairstyle}}'],
      ['unknown-name', '{{outfit}}'],
    ])
  }
  assert.deepEqual(marked('{{outfit}}'), [['named-wildcard', '{{outfit}}']])
  assert.deepEqual(marked('{a|b} {{x}} [y] ', { mode: 'raw' }), [])
  assert.deepEqual(marked('# note', { mode: 'raw' }), [])
})

test('spans cover the whole prompt, keep line breaks, and take the innermost mark', () => {
  const text = 'a {red|[blue]} coat\n# keep it'
  const spans = promptSyntaxSpans(text)
  assert.equal(spans.map(s => s.text).join(''), text)
  assert.deepEqual(spans, [
    { text: 'a ', kind: null },
    { text: '{red|', kind: 'wildcard' },
    { text: '[blue]', kind: 'verbatim' },
    { text: '}', kind: 'wildcard' },
    { text: ' coat\n', kind: null },
    { text: '# keep it', kind: 'comment' },
  ])
  assert.deepEqual(promptSyntaxSpans(''), [])
  assert.deepEqual(promptSyntaxSpans('plain words'), [{ text: 'plain words', kind: null }])
})

test('slots: the shared case file', () => {
  for (const c of SLOT_CASES) assert.deepEqual(findSlots(c.text), c.slots, c.text)
})

test('a slot is marked beside a list, not inside one, a [verbatim] or a comment', () => {
  assert.deepEqual(marked('a <young man> in a {red|blue} coat [x <y z>] <d>hi</d>'), [
    ['slot', '<young man>'],
    ['wildcard', '{red|blue}'],
    ['verbatim', '[x <y z>]'],
  ])
  assert.deepEqual(marked('# a <young man>'), [['comment', '# a <young man>']])
  assert.deepEqual(marked('<young man>', { mode: 'raw' }), [])
})

test('outside Fluent a slot is its words', () => {
  assert.equal(unwrapSlots('a <young man> [x <y z>] {<a b>|c} <d>hi</d>'), 'a young man [x <y z>] {<a b>|c} <d>hi</d>')
  assert.equal(
    processFinalPrompt('dorm room with a <young man>, <d>hi</d> <lora:x:0.8>'),
    'dorm room with a young man, <d>hi</d> <lora:x:0.8>',
  )
})
