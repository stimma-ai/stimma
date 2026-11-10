import assert from 'node:assert/strict'
import test from 'node:test'

import {
  shownOption,
  buildVocabTree,
  effectiveContext,
  groupOpen,
  layoutOptions,
  matchesQuery,
  valueFits,
  type VocabLeaf,
  type VocabTier,
} from './programVocab.ts'

test('matchesQuery needs every word, any case, any order', () => {
  assert.ok(matchesQuery('a broad toothy smile', 'Smile broad'))
  assert.ok(matchesQuery('anything', '   '))
  assert.ok(!matchesQuery('a broad toothy smile', 'smile frown'))
})

test('flat layout: pinned first whatever the query, the rest filtered', () => {
  const l = layoutOptions(['red', 'green', 'blue', 'teal'], ['teal'], 'e')
  assert.deepEqual(l.pinned, ['teal'])
  assert.deepEqual(l.flat, ['red', 'green', 'blue'])
  assert.equal(l.groups.length, 0)
  const q = layoutOptions(['red', 'green', 'blue', 'teal'], ['blue'], 'gre')
  assert.deepEqual(q.pinned, ['blue'])
  assert.deepEqual(q.flat, ['green'])
  assert.equal(q.hits, 1)
})

test('tiered layout groups in tier order; unknown values sit with the usual ones', () => {
  const tiers: Record<string, VocabTier> = { a: 'unusual', b: 'typical', c: 'generated', d: 'plausible', e: 'typical' }
  const l = layoutOptions(['a', 'b', 'c', 'd', 'e', 'mine'], ['e'], '', tiers)
  assert.deepEqual(l.pinned, ['e'])
  assert.deepEqual(l.groups.map(g => [g.tier, g.items]), [
    ['typical', ['b', 'mine']], ['plausible', ['d']], ['unusual', ['a']], ['generated', ['c']],
  ])
  assert.deepEqual(l.groups.map(g => g.label), ['Usual', 'Less usual', 'Rare', 'More ideas'])
})

test('values drawn only when picked get their own closed group, last', () => {
  const tiers: Record<string, VocabTier> = { '8–10-year-old': 'opt_in', '20–24-year-old': 'typical', '60–64-year-old': 'plausible' }
  const l = layoutOptions(Object.keys(tiers), [], '', tiers)
  assert.deepEqual(l.groups.map(g => [g.tier, g.label, g.items]), [
    ['typical', 'Usual', ['20–24-year-old']], ['plausible', 'Less usual', ['60–64-year-old']],
    ['opt_in', 'Only when picked', ['8–10-year-old']],
  ])
  assert.equal(groupOpen(l.groups[2], '', {}), false)
  // Picked, it is pinned like any other option.
  assert.deepEqual(layoutOptions(Object.keys(tiers), ['8–10-year-old'], '', tiers).pinned, ['8–10-year-old'])
})

test('search keeps group totals and opens exactly the groups with hits', () => {
  const tiers: Record<string, VocabTier> = { 'soft smile': 'typical', frown: 'typical', 'wry smile': 'unusual', scowl: 'plausible' }
  const l = layoutOptions(Object.keys(tiers), [], 'smile', tiers)
  const by = Object.fromEntries(l.groups.map(g => [g.tier, g]))
  assert.deepEqual(by.typical.items, ['soft smile'])
  assert.equal(by.typical.total, 2)
  assert.equal(l.hits, 2)
  assert.equal(groupOpen(by.unusual, 'smile', {}), true)
  assert.equal(groupOpen(by.plausible, 'smile', { plausible: true }), false)
  // No query: usual open by default, the rest closed until opened.
  assert.equal(groupOpen(by.typical, '', {}), true)
  assert.equal(groupOpen(by.unusual, '', {}), false)
  assert.equal(groupOpen(by.unusual, '', { unusual: true }), true)
  assert.equal(groupOpen(by.typical, '', { typical: false }), false)
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

test('a template shows its colour slots as an ellipsis', () => {
  assert.equal(shownOption('a {main} technical T-shirt and {accent} running shorts'), 'a … technical T-shirt and … running shorts')
  assert.equal(shownOption('a white karate gi'), 'a white karate gi')
})
