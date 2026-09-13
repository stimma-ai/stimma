import assert from 'node:assert/strict'
import test from 'node:test'

import { applyJournalForward, applyJournalInverse } from './journalReplay.ts'
import type { JournalEntry, StackDocument } from './types.ts'

function doc(edits: any[]): StackDocument {
  return {
    format: 'stimma-image-stack',
    version: 1,
    base: { asset_id: 1, revision_id: 1, media_id: 1, file_hash: 'base', width: 100, height: 100 },
    canvas: { width: 100, height: 100 },
    edits,
  } as StackDocument
}

function scopedAdjust(id: string, regions: any[]) {
  return {
    id,
    class: 'container',
    enabled: true,
    label: 'Light',
    exec: { kind: 'retouch-regions', version: 1 },
    defaults: {},
    regions,
  }
}

const legacyRegion = {
  id: 'r1', kind: 'light', enabled: true,
  mask_ref: 'payloads/base.png', settings: { exposure: 20 },
}

const compositeRegion = {
  id: 'r1', kind: 'light', enabled: true,
  mask_components: [
    { id: 'c1', mode: 'add', enabled: true, mask_ref: 'payloads/base.png', semantic: { prompt: 'sky' } },
    { id: 'c2', mode: 'intersect', enabled: true, mask: { kind: 'linear', x1: 0, y1: 0, x2: 10, y2: 10, softness: 55 } },
    { id: 'c3', mode: 'subtract', enabled: true, mask_ref: 'payloads/brush.png' },
  ],
  settings: { exposure: 20 },
}

/** The exact entry useStackDocument's setRegions records. */
function setRegionsEntry(opId: string, before: any[], after: any[]): JournalEntry {
  return {
    seq: 1,
    action: 'set_regions',
    forward: { op_id: opId, regions: after },
    inverse: { op_id: opId, regions: before },
  }
}

test('undoing a mask upgrade restores the legacy single-mask region exactly', () => {
  const d = doc([scopedAdjust('op1', [JSON.parse(JSON.stringify(compositeRegion))])])
  const entry = setRegionsEntry('op1', [legacyRegion], [compositeRegion])

  applyJournalInverse(d, entry)
  assert.deepEqual((d.edits[0] as any).regions, [legacyRegion])

  applyJournalForward(d, entry)
  assert.deepEqual((d.edits[0] as any).regions, [compositeRegion])
})

test('undo and redo of a component toggle round-trips the whole component list', () => {
  const before = JSON.parse(JSON.stringify(compositeRegion))
  const after = JSON.parse(JSON.stringify(compositeRegion))
  after.mask_components[2].enabled = false

  const d = doc([scopedAdjust('op1', [after])])
  const entry = setRegionsEntry('op1', [before], [JSON.parse(JSON.stringify(after))])

  applyJournalInverse(d, entry)
  assert.equal((d.edits[0] as any).regions[0].mask_components[2].enabled, true)

  applyJournalForward(d, entry)
  assert.equal((d.edits[0] as any).regions[0].mask_components[2].enabled, false)
  // Semantic identity survives the round trip untouched.
  assert.deepEqual(
    (d.edits[0] as any).regions[0].mask_components[0].semantic,
    { prompt: 'sky' },
  )
})

test('undoing a modifier removal restores it at its place in the composition', () => {
  const before = JSON.parse(JSON.stringify(compositeRegion))
  const after = JSON.parse(JSON.stringify(compositeRegion))
  after.mask_components.splice(1, 1) // delete the Intersect · Linear gradient

  const d = doc([scopedAdjust('op1', [JSON.parse(JSON.stringify(after))])])
  const entry = setRegionsEntry('op1', [before], [after])

  applyJournalInverse(d, entry)
  const restored = (d.edits[0] as any).regions[0].mask_components
  assert.equal(restored.length, 3)
  assert.equal(restored[1].id, 'c2')
  assert.equal(restored[1].mode, 'intersect')
})

test('removing the whole scoped op and undoing brings its composition back', () => {
  const op = scopedAdjust('op1', [JSON.parse(JSON.stringify(compositeRegion))])
  const d = doc([op])
  const entry: JournalEntry = {
    seq: 1,
    action: 'remove_op',
    forward: { op_id: 'op1' },
    inverse: { op: JSON.parse(JSON.stringify(op)), index: 0 },
  }
  applyJournalForward(d, entry)
  assert.equal(d.edits.length, 0)
  applyJournalInverse(d, entry)
  assert.equal(d.edits.length, 1)
  assert.equal(
    (d.edits[0] as any).regions[0].mask_components.length, 3,
  )
})

test('reorder round-trips leave region compositions untouched', () => {
  const a = scopedAdjust('a', [JSON.parse(JSON.stringify(compositeRegion))])
  const b = { id: 'b', class: 'parametric', enabled: true, label: 'Crop', exec: { kind: 'crop' }, params: {} }
  const d = doc([a, b])
  const entry: JournalEntry = {
    seq: 1,
    action: 'reorder_ops',
    forward: { order: ['b', 'a'] },
    inverse: { order: ['a', 'b'] },
  }
  applyJournalForward(d, entry)
  assert.deepEqual(d.edits.map(op => op.id), ['b', 'a'])
  applyJournalInverse(d, entry)
  assert.deepEqual(d.edits.map(op => op.id), ['a', 'b'])
  assert.equal((d.edits[0] as any).regions[0].mask_components.length, 3)
})
