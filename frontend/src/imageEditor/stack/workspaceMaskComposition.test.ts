import assert from 'node:assert/strict'
import test from 'node:test'

import {
  GESTURE_TOOL_LABELS,
  appendWorkspaceMaskGesture,
} from './workspaceMaskComposition.ts'
import { captureAdjustmentScope } from './adjustmentScope.ts'
import type { WorkspaceMaskGesture } from './workspaceMaskComposition.ts'

type Mask = { name: string }
const mask = (name: string): Mask => ({ name })
const merge = (a: Mask, b: Mask): Mask => ({ name: `${a.name}+${b.name}` })

test('the reported case: sky, then intersect rectangle, keeps both ingredients', () => {
  // AI "sky" lands on an empty workspace…
  let composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'new',
    hadSelection: false,
    mask: mask('sky-raster'),
    semantic: { prompt: 'sky' },
  })
  // …then a rectangle intersects it.
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'intersect',
    hadSelection: true,
    mask: mask('rect-raster'),
    label: GESTURE_TOOL_LABELS.rect,
  })
  assert.equal(composition?.length, 2)
  assert.deepEqual(composition![0].semantic, { prompt: 'sky' })
  assert.equal(composition![0].mode, 'add')
  assert.equal(composition![1].mode, 'intersect')
  assert.equal(composition![1].label, 'Rectangle')

  // And the Adjust click captures it as a composition scope, by copy.
  const scope = captureAdjustmentScope<Mask>(
    mask('flattened'),
    source => ({ ...source }),
    null, null,
    'frame-a',
    null, null,
    composition,
    'frame-a',
  )
  assert.equal(scope?.kind, 'composition')
  if (scope?.kind === 'composition') {
    assert.equal(scope.entries.length, 2)
    assert.deepEqual(scope.entries[0].semantic, { prompt: 'sky' })
    // Copies, not references: mutating the composition later must not touch it.
    composition![1].mode = 'add'
    assert.equal(scope.entries[1].mode, 'intersect')
  }
})

test('a New gesture restarts the composition as the base', () => {
  let composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'new', hadSelection: false, mask: mask('a'),
  })
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'subtract', hadSelection: true, mask: mask('b'),
  })
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'new', hadSelection: true, mask: mask('c'), label: 'Lasso',
  })
  assert.equal(composition?.length, 1)
  assert.equal(composition![0].mode, 'add')
  assert.equal(composition![0].mask?.name, 'c')
})

test('a combining gesture on an empty workspace still seeds the base', () => {
  const composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'add', hadSelection: false, mask: mask('brush'), label: 'Brush',
  })
  assert.equal(composition?.length, 1)
  assert.equal(composition![0].mode, 'add')
})

test('combining onto an untracked selection resigns to null', () => {
  const composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'intersect', hadSelection: true, mask: mask('rect'),
  })
  assert.equal(composition, null)
})

test('consecutive same-mode brush strokes merge into one component', () => {
  let composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'new', hadSelection: false, mask: mask('sky'), semantic: { prompt: 'sky' },
  })
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'subtract', hadSelection: true, mask: mask('s1'), label: 'Brush',
  }, merge)
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'subtract', hadSelection: true, mask: mask('s2'), label: 'Brush',
  }, merge)
  assert.equal(composition?.length, 2)
  assert.equal(composition![1].label, 'Brush')
  assert.equal(composition![1].mask?.name, 's1+s2')
  // A brush in a DIFFERENT mode is a new idea, not an extension.
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'add', hadSelection: true, mask: mask('s3'), label: 'Brush',
  }, merge)
  assert.equal(composition?.length, 3)
})

test('gradient gestures keep geometry, not pixels', () => {
  let composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'new', hadSelection: false, mask: mask('sky'), semantic: { prompt: 'sky' },
  })
  const gradient = { kind: 'linear' as const, x1: 0, y1: 0, x2: 10, y2: 10, softness: 55 }
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'intersect', hadSelection: true, gradient,
  })
  assert.equal(composition?.length, 2)
  assert.deepEqual(composition![1].gradient, gradient)
  assert.equal(composition![1].mask, undefined)
  // A copy: re-aiming the workspace draft later must not rewrite the entry.
  gradient.x2 = 999
  assert.equal(composition![1].gradient?.x2, 10)
})

test('object-pick cycling replaces the previous entry instead of stacking', () => {
  let composition = appendWorkspaceMaskGesture<Mask>(null, {
    combine: 'new', hadSelection: false, mask: mask('sky'), semantic: { prompt: 'sky' },
  })
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'add', hadSelection: true, mask: mask('object-coarse'), label: 'Object',
  })
  composition = appendWorkspaceMaskGesture(composition, {
    combine: 'add', hadSelection: true, mask: mask('object-fine'), label: 'Object',
    replacesPrevious: true,
  })
  assert.equal(composition?.length, 2)
  assert.equal(composition![1].mask?.name, 'object-fine')
})

test('one tracked gesture stays a plain raster scope, not a one-row composition', () => {
  const composition: WorkspaceMaskGesture<Mask>[] = [
    { mode: 'add', mask: mask('only') },
  ]
  const scope = captureAdjustmentScope<Mask>(
    mask('flattened'),
    source => ({ ...source }),
    null, null, 'frame-a', null, null, composition, 'frame-a',
  )
  assert.equal(scope?.kind, 'raster')
})

test('a composition pinned to another frame is not captured', () => {
  const composition: WorkspaceMaskGesture<Mask>[] = [
    { mode: 'add', mask: mask('a') },
    { mode: 'intersect', mask: mask('b') },
  ]
  const scope = captureAdjustmentScope<Mask>(
    mask('flattened'),
    source => ({ ...source }),
    null, null, 'current-frame', null, null, composition, 'old-frame',
  )
  assert.equal(scope?.kind, 'raster')
})
