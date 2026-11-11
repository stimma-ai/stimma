import assert from 'node:assert/strict'
import test from 'node:test'

import { lineSyntaxRanges, promptSyntaxSpans } from './promptSyntax.ts'

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

test('plain mode flags only {{names}} nothing can fill; raw marks nothing', () => {
  const known = new Set(['hairstyle'])
  assert.deepEqual(marked('{{Hairstyle}} {{outfit}}', { mode: 'plain', known }), [
    ['named-wildcard', '{{Hairstyle}}'],
    ['needs-model', '{{outfit}}'],
  ])
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
