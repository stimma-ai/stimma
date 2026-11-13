import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { findLists, findSlots, lineSyntaxRanges, promptSyntaxSpans, slotAt, slotWrapRange, usableVaryPhrases } from './promptSyntax.ts'
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

test('a slot is found by its place among the prompt\'s slots, comments and verbatim left out', () => {
  const text = '# a <note>\n[x <y z>] a <young man>, {<a b>|c}\nlit by <light>'
  const young = text.indexOf('<young man>')
  assert.deepEqual(slotAt(text, young), { n: 1, from: young, to: young + 11, words: 'young man' })
  assert.deepEqual(slotAt(text, young + 10), { n: 1, from: young, to: young + 11, words: 'young man' })
  assert.equal(slotAt(text, young + 11), null)
  assert.equal(slotAt(text, text.indexOf('<note>') + 1), null)
  assert.equal(slotAt(text, text.indexOf('<y z>') + 1), null)
  assert.equal(slotAt(text, text.indexOf('<light>') + 2)?.n, 2)
})

test('selected words become a slot only where the grammar reads one', () => {
  const wrap = (text: string, words: string) => {
    const i = text.indexOf(words)
    const at = slotWrapRange(text, i, i + words.length)
    return at && text.slice(at[0], at[1])
  }
  const line = 'dorm room with a young man, a {red|blue} coat, {{hairstyle}}, [ohwx woman] <pet>'
  assert.equal(wrap(line, 'young man'), 'young man')
  assert.equal(wrap(line, ' young man, '), 'young man,')  // trimmed of spaces only
  assert.equal(wrap(line, 'dorm room'), 'dorm room')
  assert.equal(wrap(line, 'red'), null)  // inside a list
  assert.equal(wrap(line, 'a {red|blue}'), null)  // touches a list
  assert.equal(wrap(line, 'hairstyle'), null)
  assert.equal(wrap(line, 'ohwx'), null)
  assert.equal(wrap(line, 'pet'), null)  // already a slot
  assert.equal(wrap(line, 'oom'), null)  // inside a word
  assert.equal(wrap(line, 'a'), null)  // one character
  assert.equal(wrap('# a young man', 'young man'), null)
  assert.equal(wrap('a young\nman', 'young\nman'), null)
  assert.equal(wrap('weight: heavy', 'weight: heavy'), null)
  assert.equal(wrap('   ', '  '), null)
  assert.deepEqual(slotWrapRange('a young man', 11, 2), [2, 11])  // a backwards selection
  assert.equal(wrap('# note\na young man', 'young man'), 'young man')
})

test('suggested phrases are kept only while they stand as sent, and never overlap', () => {
  const text = 'dorm room with a young man and a {red|blue} coat'
  const at = (words: string) => ({ from: text.indexOf(words), to: text.indexOf(words) + words.length, text: words })
  assert.deepEqual(usableVaryPhrases(text, [at('young man'), at('dorm room'), at('red'), at('room with'), { from: 0, to: 4, text: 'room' }]), [
    at('dorm room'), at('young man'),
  ])
})

test('the user’s own lists, in order, with their options; not in comments or names', () => {
  const text = 'a {summer| autumn} and {{hair}} {x|{y|z}}\n# {no|pe}\n{red|blue}'
  assert.deepEqual(findLists(text).map(l => [text.slice(l.from, l.to), l.items]), [
    ['{summer| autumn}', ['summer', 'autumn']], ['{x|{y|z}}', ['x', '{y|z}']], ['{red|blue}', ['red', 'blue']],
  ])
})
