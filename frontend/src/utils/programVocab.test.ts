import assert from 'node:assert/strict'
import test from 'node:test'

import {
  shownOption,
  buildVocabTree,
  effectiveContext,
  matchesQuery,
  partLabel,
  shownOptions,
  standbyOf,
  valueFits,
  type VocabLeaf,
  type VocabTier,
} from './programVocab.ts'

test('matchesQuery needs every word, any case, any order', () => {
  assert.ok(matchesQuery('a broad toothy smile', 'Smile broad'))
  assert.ok(matchesQuery('anything', '   '))
  assert.ok(!matchesQuery('a broad toothy smile', 'smile frown'))
})

test('shownOptions keeps the list order, filtered by the search and the part chosen', () => {
  const options = ['jet black', 'dark brown', 'ash brown', 'honey blonde', 'mine']
  const parts = { name: 'shade', values: ['black', 'brunette', 'blonde'], of: { 'jet black': 'black', 'dark brown': 'brunette', 'ash brown': 'brunette', 'honey blonde': 'blonde' } }
  assert.equal(shownOptions(options, '  ', null, parts), options)
  assert.deepEqual(shownOptions(options, 'BROWN'), ['dark brown', 'ash brown'])
  assert.deepEqual(shownOptions(options, '', 'brunette', parts), ['dark brown', 'ash brown'])
  assert.deepEqual(shownOptions(options, 'ash', 'brunette', parts), ['ash brown'])
  // an option the list doesn't know (one the person added) has no part
  assert.deepEqual(shownOptions(options, 'mine', 'blonde', parts), [])
  assert.equal(partLabel('strawberry_blonde'), 'strawberry blonde')
})

test('standbyOf names the values drawn only when ticked', () => {
  const tiers: Record<string, VocabTier> = { '8–10-year-old': 'opt_in', '20–24-year-old': 'typical', '60–64-year-old': 'plausible' }
  assert.deepEqual([...standbyOf({ tiers })], ['8–10-year-old'])
  assert.equal(standbyOf(null).size, 0)
})

const leaf = (over: Partial<VocabLeaf>): VocabLeaf => ({
  id: 'x', label: 'X', description: '', pos: '', frame: '', notes: '', facets: [], closed: false, untagged: {}, values: [], ...over,
})

test('valueFits: tag, else untagged, else everything; "any" fits all', () => {
  const ctx = effectiveContext({ genre: 'realistic', era: 'contemporary', space: null }, { era: 'medieval' })
  assert.deepEqual(ctx, { genre: 'realistic', era: 'medieval' })
  const l = leaf({ untagged: { genre: ['realistic'] } })
  assert.ok(valueFits(l, {}, ctx))
  assert.ok(!valueFits(l, {}, { genre: 'fantasy' }))
  assert.ok(valueFits(l, { tags: { genre: ['fantasy'] } }, { genre: 'fantasy' }))
  assert.ok(!valueFits(l, { tags: { era: ['contemporary'] } }, ctx))
  assert.ok(valueFits(l, { tags: { era: 'any', genre: 'any' } }, { genre: 'scifi', era: 'future' }))
  assert.ok(valueFits(leaf({}), {}, { genre: 'horror', space: 'indoor' }))
})

test('buildVocabTree nests by longest node prefix and counts values', () => {
  const v = (n: number) => Array.from({ length: n }, (_, i) => ({ text: `v${i}`, tier: 'typical' as const }))
  const tree = buildVocabTree(
    [{ id: 'person', label: 'Person', description: '' }, { id: 'person.outfit', label: 'Outfit', description: '' }],
    [
      leaf({ id: 'person.expression', label: 'Expression', values: v(3) }),
      leaf({ id: 'person.outfit.casual', label: 'Casual', values: v(2) }),
      leaf({ id: 'camera.lens', label: 'Lens', values: v(1) }),
    ],
  )
  assert.deepEqual(tree.map(n => [n.id, n.count]), [['camera', 1], ['person', 5]])
  const person = tree[1]
  assert.deepEqual(person.leaves.map(l => l.id), ['person.expression'])
  assert.deepEqual(person.children.map(c => [c.id, c.count, c.leaves.map(l => l.id)]), [['person.outfit', 2, ['person.outfit.casual']]])
})

test('a template shows its color slots as an ellipsis', () => {
  assert.equal(shownOption('a {main} technical T-shirt and {accent} running shorts'), 'a … technical T-shirt and … running shorts')
  assert.equal(shownOption('a white karate gi'), 'a white karate gi')
})
