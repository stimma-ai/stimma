import assert from 'node:assert/strict'
import test from 'node:test'

import {
  componentHasCoverage,
  composeMaskAlpha,
  generativeOpHasEditableMask,
  hasMaskComponents,
  legacyBaseComponentId,
  maskComponentLabel,
  maskComponentModeLabel,
  opMaskComponents,
  regionMaskComponents,
  regionWithMaskComponents,
} from './maskComponents.ts'
import { transformGradientMask } from './regionMask.ts'
import type { MaskComponent, RetouchRegion } from './types.ts'

const alpha = (...values: number[]) => new Uint8ClampedArray(values)

function entry(
  values: number[] | null,
  mode: MaskComponent['mode'] = 'add',
  enabled = true,
) {
  return { alpha: values ? alpha(...values) : null, mode, enabled }
}

// -- composition math --------------------------------------------------------

test('a lone base is its own coverage', () => {
  // The base is written with mode 'add', so seeding IS the ordinary rule.
  assert.deepEqual(
    Array.from(composeMaskAlpha([entry([0, 128, 255])], 3)),
    [0, 128, 255],
  )
})

test('add is a soft union: max, not sum', () => {
  const composed = composeMaskAlpha(
    [entry([0, 128, 200]), entry([64, 128, 100], 'add')],
    3,
  )
  assert.deepEqual(Array.from(composed), [64, 128, 200])
})

test('subtract multiplies by the complement', () => {
  const composed = composeMaskAlpha(
    [entry([255, 255, 128]), entry([0, 255, 128], 'subtract')],
    3,
  )
  // 255×1, 255×0, 128×(1−0.502…) — soft edges erode softly.
  assert.deepEqual(Array.from(composed), [255, 0, 64])
})

test('intersect multiplies coverages', () => {
  const composed = composeMaskAlpha(
    [entry([255, 128, 0]), entry([128, 128, 255], 'intersect')],
    3,
  )
  assert.deepEqual(Array.from(composed), [128, 64, 0])
})

test('components compose in order, top-down', () => {
  // (base ∪ add) × intersect, then eroded by subtract.
  const composed = composeMaskAlpha(
    [
      entry([255, 0]),
      entry([0, 255], 'add'),
      entry([255, 128], 'intersect'),
      entry([255, 0], 'subtract'),
    ],
    2,
  )
  assert.deepEqual(Array.from(composed), [0, 128])
})

test('a disabled component is skipped without reordering the rest', () => {
  const composed = composeMaskAlpha(
    [
      entry([255, 255]),
      entry([255, 255], 'subtract', false),
      entry([128, 255], 'intersect'),
    ],
    2,
  )
  assert.deepEqual(Array.from(composed), [128, 255])
})

test('a disabled base leaves nothing for intersect and everything for add', () => {
  // Intersecting no coverage keeps no coverage; adding to none is the add.
  const withIntersect = composeMaskAlpha(
    [entry([255, 255], 'add', false), entry([255, 255], 'intersect')],
    2,
  )
  assert.deepEqual(Array.from(withIntersect), [0, 0])
  const withAdd = composeMaskAlpha(
    [entry([255, 255], 'add', false), entry([64, 128], 'add')],
    2,
  )
  assert.deepEqual(Array.from(withAdd), [64, 128])
})

test('a component with no alpha yet contributes nothing rather than blacking out', () => {
  const composed = composeMaskAlpha(
    [entry([200, 100]), entry(null, 'intersect')],
    2,
  )
  assert.deepEqual(Array.from(composed), [200, 100])
})

test('an empty composition composes to no coverage', () => {
  assert.deepEqual(Array.from(composeMaskAlpha([], 2)), [0, 0])
})

// -- the component view of a region ------------------------------------------

function legacyRasterRegion(): RetouchRegion {
  return {
    id: 'r1',
    kind: 'light',
    enabled: true,
    mask_ref: 'payloads/mask.png',
    payload_origin: [4, 6],
    payload_to_document: [1, 0, 0, 1, 4, 6],
    payload_frame: { matrix: [1, 0, 0, 1, 0, 0], width: 100, height: 80 },
    settings: {} as any,
  }
}

test('a legacy raster region reads as one base component sharing its anchors', () => {
  const region = legacyRasterRegion()
  assert.equal(hasMaskComponents(region), false)
  const components = regionMaskComponents(region)
  assert.equal(components.length, 1)
  assert.equal(components[0].id, legacyBaseComponentId(region))
  assert.equal(components[0].mode, 'add')
  assert.equal(components[0].enabled, true)
  assert.equal(components[0].mask_ref, 'payloads/mask.png')
  assert.deepEqual(components[0].payload_origin, [4, 6])
  assert.deepEqual(components[0].payload_to_document, [1, 0, 0, 1, 4, 6])
  assert.deepEqual(components[0].payload_frame?.matrix, [1, 0, 0, 1, 0, 0])
  // A view, not a migration: the stored region is untouched.
  assert.equal(region.mask_components, undefined)
})

test('a legacy gradient region reads as one parametric base component', () => {
  const region: RetouchRegion = {
    id: 'r2',
    kind: 'color',
    enabled: true,
    mask: { kind: 'linear', x1: 0, y1: 0, x2: 10, y2: 10, softness: 55 },
    settings: {} as any,
  }
  const components = regionMaskComponents(region)
  assert.equal(components.length, 1)
  assert.deepEqual(components[0].mask, region.mask)
  assert.equal(components[0].mask_ref, undefined)
  assert.equal(componentHasCoverage(components[0]), true)
})

test('a region with no coverage yet has no components', () => {
  const region: RetouchRegion = {
    id: 'r3', kind: 'light', enabled: true, settings: {} as any,
  }
  assert.deepEqual(regionMaskComponents(region), [])
})

test('an explicit component list is authoritative over legacy fields', () => {
  const region = legacyRasterRegion()
  region.mask_components = [
    { id: 'c1', mode: 'add', enabled: true, mask_ref: 'payloads/other.png' },
  ]
  const components = regionMaskComponents(region)
  assert.equal(components.length, 1)
  assert.equal(components[0].id, 'c1')
})

test('upgrading a region clears the legacy single-mask authority', () => {
  const region = legacyRasterRegion()
  const components = regionMaskComponents(region)
  const upgraded = regionWithMaskComponents(region, [
    ...components,
    { id: 'c2', mode: 'subtract', enabled: true, mask_ref: 'payloads/brush.png' },
  ])
  assert.equal(upgraded.mask_components?.length, 2)
  assert.equal(upgraded.mask, undefined)
  assert.equal(upgraded.mask_ref, undefined)
  assert.equal(upgraded.payload_origin, undefined)
  assert.equal(upgraded.payload_to_document, undefined)
  // The base component keeps the payload and the anchors the region had.
  assert.equal(upgraded.mask_components?.[0].mask_ref, 'payloads/mask.png')
  assert.deepEqual(upgraded.mask_components?.[0].payload_to_document, [1, 0, 0, 1, 4, 6])
  // Round trip through JSON — the persisted document drops nothing it needs.
  const persisted = JSON.parse(JSON.stringify(upgraded))
  assert.equal(persisted.mask_components.length, 2)
  assert.equal(persisted.mask_ref, undefined)
})

test('coverage requires geometry with extent or a payload', () => {
  assert.equal(
    componentHasCoverage({ mask_ref: 'payloads/m.png' }),
    true,
  )
  assert.equal(componentHasCoverage({}), false)
  assert.equal(
    componentHasCoverage({
      mask: { kind: 'linear', x1: 5, y1: 5, x2: 5, y2: 5, softness: 0 },
    }),
    false,
  )
})

// -- component gradient geometry through a crop ------------------------------

test('a gradient component co-transforms through its own authored frame', () => {
  // The component was authored in a 100×80 frame; a later crop maps that
  // frame by translate(-20,-10). The ramp's endpoints follow the pixels.
  const component: MaskComponent = {
    id: 'c1',
    mode: 'intersect',
    enabled: true,
    mask: { kind: 'linear', x1: 30, y1: 20, x2: 70, y2: 60, softness: 55 },
  }
  const carried = transformGradientMask(
    component.mask as any,
    [1, 0, 0, 1, -20, -10],
  )
  assert.deepEqual(
    carried,
    { kind: 'linear', x1: 10, y1: 10, x2: 50, y2: 50, softness: 55 },
  )
})

// -- pixel identity ----------------------------------------------------------

test('mask components participate in the container pixel identity', async () => {
  const { stackHashes } = await import('./stackHashes.ts')
  const region = legacyRasterRegion()
  const withComponents = regionWithMaskComponents(region, [
    ...regionMaskComponents(region),
    { id: 'c2', mode: 'subtract', enabled: true, mask_ref: 'payloads/brush.png' },
  ])
  const container = (regions: any[]) => ({
    format: 'stimma-image-stack', version: 1,
    base: { asset_id: 1, revision_id: 1, media_id: 1, file_hash: 'base', width: 10, height: 10 },
    canvas: { width: 10, height: 10 },
    edits: [{
      id: 'op1', class: 'container', enabled: true, label: 'Light',
      exec: { kind: 'retouch-regions', version: 1 }, defaults: {}, regions,
    }],
  }) as any
  const before = stackHashes(container([region])).head
  const after = stackHashes(container([withComponents])).head
  // Editing the composition invalidates the composite above it, with no new
  // dirty logic anywhere.
  assert.notEqual(before, after)
  // Toggling one component off is itself a distinct pixel identity.
  const toggled = JSON.parse(JSON.stringify(withComponents))
  toggled.mask_components[1].enabled = false
  assert.notEqual(after, stackHashes(container([toggled])).head)
})

// -- labels ------------------------------------------------------------------

test('component rows name themselves by what they are', () => {
  assert.equal(
    maskComponentLabel({ id: 'c', mode: 'add', enabled: true, semantic: { prompt: 'sky' } }),
    'Sky',
  )
  assert.equal(
    maskComponentLabel({ id: 'c', mode: 'add', enabled: true, semantic: { intent: 'subject' } }),
    'Subject',
  )
  assert.equal(
    maskComponentLabel({ id: 'c', mode: 'add', enabled: true, semantic: { intent: 'sky' } }),
    'Sky',
  )
  assert.equal(
    maskComponentLabel({
      id: 'c', mode: 'add', enabled: true,
      mask: { kind: 'radial', cx: 0, cy: 0, rx: 5, ry: 5, feather: 60, invert: false },
    }),
    'Radial gradient',
  )
  assert.equal(
    maskComponentLabel({ id: 'c', mode: 'add', enabled: true, mask_ref: 'p.png' }),
    'Selection',
  )
  assert.equal(
    maskComponentLabel({ id: 'c', mode: 'add', enabled: true, label: 'Brush' }),
    'Brush',
  )
})

test('the base wears no mode prefix; modifiers wear theirs', () => {
  assert.equal(maskComponentModeLabel({ mode: 'add' }, 0), null)
  assert.equal(maskComponentModeLabel({ mode: 'add' }, 1), 'Add')
  assert.equal(maskComponentModeLabel({ mode: 'subtract' }, 2), 'Subtract')
  assert.equal(maskComponentModeLabel({ mode: 'intersect' }, 1), 'Intersect')
})

test('an orphaned modifier left first keeps its prefix instead of posing as base', () => {
  // Its base was deleted; it still subtracts/intersects against nothing, and
  // the row must say so rather than display it as coverage.
  assert.equal(maskComponentModeLabel({ mode: 'subtract' }, 0), 'Subtract')
  assert.equal(maskComponentModeLabel({ mode: 'intersect' }, 0), 'Intersect')
})

// -- generative op masks -----------------------------------------------------

function patchOp(extra: any = {}) {
  return {
    id: 'g1', class: 'patch', enabled: true, label: 'Remove',
    exec: { kind: 'tool', tool_id: 't', task_type: 'inpaint-image' },
    params: {}, picked: null, candidates: [],
    mask_ref: 'payloads/submitted.png',
    payload_to_document: [1, 0, 0, 1, 0, 0],
    payload_frame: { matrix: [1, 0, 0, 1, 0, 0], width: 100, height: 80 },
    ...extra,
  }
}

test('a generative op with only its submission mask reads as one luminance base', () => {
  const components = opMaskComponents(patchOp())
  assert.equal(components.length, 1)
  assert.equal(components[0].mask_ref, 'payloads/submitted.png')
  assert.equal(components[0].luminance, true)
  assert.equal(components[0].mode, 'add')
  assert.deepEqual(components[0].payload_to_document, [1, 0, 0, 1, 0, 0])
})

test('an explicit generative component list is authoritative; mask_ref survives beside it', () => {
  const op = patchOp({
    mask_components: [
      { id: 'c1', mode: 'add', enabled: true, mask_ref: 'payloads/submitted.png', luminance: true },
      { id: 'c2', mode: 'subtract', enabled: true, mask_ref: 'payloads/brush.png' },
    ],
  })
  const components = opMaskComponents(op)
  assert.equal(components.length, 2)
  assert.equal(components[1].mode, 'subtract')
  // The sampled-through record is untouched by the upgrade.
  assert.equal(op.mask_ref, 'payloads/submitted.png')
})

test('expand and cutout masks are not editable; ordinary masked generation is', () => {
  assert.equal(generativeOpHasEditableMask(patchOp()), true)
  assert.equal(generativeOpHasEditableMask(patchOp({ operation: 'remove' })), true)
  assert.equal(generativeOpHasEditableMask(patchOp({ operation: 'expand' })), false)
  assert.equal(generativeOpHasEditableMask(patchOp({ operation: 'cutout' })), false)
  assert.equal(generativeOpHasEditableMask(patchOp({ mask_ref: undefined })), false)
  assert.equal(generativeOpHasEditableMask({ class: 'parametric' }), false)
})

test('generative mask components participate in the op pixel identity', async () => {
  const { stackHashes } = await import('./stackHashes.ts')
  const docOf = (op: any) => ({
    format: 'stimma-image-stack', version: 1,
    base: { asset_id: 1, revision_id: 1, media_id: 1, file_hash: 'base', width: 10, height: 10 },
    canvas: { width: 10, height: 10 },
    edits: [op],
  }) as any
  const plain = stackHashes(docOf(patchOp())).head
  const composed = stackHashes(docOf(patchOp({
    mask_components: [{ id: 'c1', mode: 'add', enabled: true, mask_ref: 'payloads/submitted.png', luminance: true }],
  }))).head
  assert.notEqual(plain, composed)
})
