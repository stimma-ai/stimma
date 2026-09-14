import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  resolveResolution,
  defaultResolutionPolicy,
  policyWithDims,
  applyCarriedPolicy,
  carriedPolicy,
  tierGroups,
  megapixelBounds,
  megapixelSliderBounds,
  RATIO_CHOICES,
  matchingRatio,
  customRatio,
  type ResolutionPolicy,
} from './resolutionPolicy.ts'

const freeform = { width: { default: 1024, 'x-step': 16, minimum: 256, maximum: 4096 }, height: { default: 1024, 'x-step': 16, minimum: 256, maximum: 4096 } }
const video: [number, number][] = [
  [832, 480], [1280, 720], [1920, 1080],
  [480, 832], [720, 1280], [1080, 1920],
  [480, 480], [720, 720], [1080, 1080],
  [640, 480], [960, 720], [1440, 1080],
  [480, 640], [720, 960], [1080, 1440],
]
const videoProps = { width: { default: 1280, 'x-allowed-dimensions': video }, height: { default: 720 } }
const lightningProps = { width: { default: 1280, 'x-allowed-dimensions': video.filter(([w, h]) => Math.min(w, h) < 1080) }, height: { default: 720 } }

const fixed = (ratio: string, mp: number): ResolutionPolicy => ({ ratio, mp, tier: 720, followShape: false, followSize: false })
const follow = (p: Partial<ResolutionPolicy> = {}): ResolutionPolicy => ({ ratio: '1:1', mp: 2, tier: 720, followShape: true, followSize: true, ...p })

test('t2i: fixed ratio at a budget', () => {
  const r = resolveResolution(fixed('16:9', 2), null, freeform)
  assert.equal(r.ratioChoice, '16:9')
  assert.ok(Math.abs(r.mp - 2) < 0.1, `mp ${r.mp}`)
  assert.equal(r.width % 16, 0)
  assert.equal(r.shapeFromImage, false)
})

test('following with no image uses the fixed values', () => {
  const r = resolveResolution(follow({ ratio: '3:4', mp: 2 }), null, freeform)
  assert.equal(r.ratioChoice, '3:4')
  assert.equal(r.shapeFromImage, false)
  assert.equal(r.sizeFromImage, false)
})

test('edit: both follow → same as the image', () => {
  const r = resolveResolution(follow(), { width: 1216, height: 1344 }, freeform)
  assert.deepEqual([r.width, r.height], [1216, 1344])
  assert.ok(r.shapeFromImage && r.sizeFromImage)
})

test('image shape at a capped budget', () => {
  const r = resolveResolution(follow({ followSize: false, mp: 1 }), { width: 4000, height: 3000 }, freeform)
  assert.ok(Math.abs(r.width / r.height - 4 / 3) < 0.03)
  assert.ok(Math.abs(r.mp - 1) < 0.1, `mp ${r.mp}`)
  assert.equal(r.ratioChoice, '4:3')
})

test('fixed ratio at the image size', () => {
  const r = resolveResolution(follow({ followShape: false, ratio: '16:9' }), { width: 1000, height: 1000 }, freeform)
  assert.equal(r.ratioChoice, '16:9')
  assert.ok(Math.abs(r.mp - 1) < 0.1)
  assert.ok(r.cropWarning)
})

test('typed dims are preserved exactly through policyWithDims', () => {
  const p = policyWithDims(fixed('1:1', 1), 1216, 1344)
  assert.equal(p.ratio, customRatio(1216, 1344))
  const r = resolveResolution(p, null, freeform)
  assert.deepEqual([r.width, r.height], [1216, 1344])
  assert.equal(r.ratioChoice, null)
  assert.equal(r.ratioLabel, '~1:1')
})

test('video: image shape at the tool tier', () => {
  const p: ResolutionPolicy = { ratio: '16:9', mp: 0.9, tier: 720, followShape: true, followSize: false }
  const r = resolveResolution(p, { width: 1536, height: 2048, name: 'still.png' }, videoProps)
  assert.deepEqual([r.width, r.height], [720, 960])
  assert.equal(r.tier, 720)
  assert.equal(r.cropWarning, null)
})

test('video: forced 16:9 from a 3:4 still warns about the crop', () => {
  const p: ResolutionPolicy = { ratio: '16:9', mp: 0.9, tier: 720, followShape: false, followSize: false }
  const r = resolveResolution(p, { width: 1536, height: 2048, name: 'still.png' }, videoProps)
  assert.deepEqual([r.width, r.height], [1280, 720])
  assert.match(r.cropWarning!, /still.png is 3:4/)
})

test('video: size from image picks the nearest tier by area', () => {
  const r = resolveResolution(follow({ ratio: '16:9' }), { width: 1920, height: 1080 }, videoProps)
  assert.deepEqual([r.width, r.height], [1920, 1080])
})

test('video: missing tier degrades with a note', () => {
  const p: ResolutionPolicy = { ratio: '16:9', mp: 2, tier: 1080, followShape: false, followSize: false }
  const r = resolveResolution(p, null, lightningProps)
  assert.deepEqual([r.width, r.height], [1280, 720])
  assert.equal(r.tierMissing, true)
})

test('tier groups are tallest first with pairs by area', () => {
  const g = tierGroups(video)
  assert.equal(g[0].ratio, '9:16')
  assert.equal(g[g.length - 1].ratio, '16:9')
  assert.deepEqual(g[g.length - 1].pairs, [[832, 480], [1280, 720], [1920, 1080]])
})

test('defaults: image tools match the image, video tools keep their tier, t2i is fixed', () => {
  const t2i = defaultResolutionPolicy(freeform, false)
  assert.equal(t2i.followShape, false)
  assert.equal(t2i.ratio, '1:1')
  assert.equal(t2i.mp, 1)
  const i2i = defaultResolutionPolicy(freeform, true)
  assert.ok(i2i.followShape && i2i.followSize)
  const i2v = defaultResolutionPolicy(videoProps, true)
  assert.equal(i2v.followShape, true)
  assert.equal(i2v.followSize, false)
  assert.equal(i2v.tier, 720)
  assert.equal(i2v.ratio, '16:9')
})

test('hop: shape travels, size stays with the target', () => {
  const src: ResolutionPolicy = { ratio: '16:9', mp: 0.9, tier: 720, followShape: false, followSize: false }
  const resolved = resolveResolution(src, { width: 1536, height: 2048 }, videoProps)
  const carried = carriedPolicy(src, resolved)
  assert.deepEqual(carried, { ratio: '16:9', followShape: false })
  const target: ResolutionPolicy = { ratio: '1:1', mp: 1, tier: 720, followShape: true, followSize: false }
  const applied = applyCarriedPolicy(target, carried, true)
  assert.equal(applied.ratio, '16:9')
  assert.equal(applied.followShape, false)
  assert.equal(applied.tier, 720)
})

test('hop: a followed shape resolves to a concrete ratio for a t2i target', () => {
  const src = follow()
  const resolved = resolveResolution(src, { width: 1536, height: 2048 }, freeform)
  const carried = carriedPolicy(src, resolved)
  assert.equal(carried.ratio, '3:4')
  const t2i = applyCarriedPolicy(fixed('1:1', 2), carried, false)
  assert.equal(t2i.ratio, '3:4')
  assert.equal(t2i.followShape, false)
})

test('hop: into an editor that matches the image, shape follows too', () => {
  const carried = { ratio: '16:9', followShape: false }
  const editor = applyCarriedPolicy(follow(), carried, true)
  assert.equal(editor.followShape, true)
})

test('matchingRatio tolerance', () => {
  assert.equal(matchingRatio(1216, 1344), null)
  assert.equal(matchingRatio(1024, 1365), '3:4')
})

test('megapixel bounds follow the per-axis limits at the current ratio', () => {
  const props = { width: { minimum: 128, maximum: 2048, 'x-step': 16 }, height: { minimum: 128, maximum: 2048, 'x-step': 16 } }
  const sq = megapixelBounds(props, 1)
  assert.equal(sq.max, 4)
  const wide = megapixelBounds(props, 4 / 3)
  assert.equal(wide.max, 3)
  assert.ok(Math.abs(wide.min - 0.0208) < 0.001, `4:3 min ${wide.min}`)
})

test('local slider stays at 4 MP across shapes while custom dimensions stay legal', () => {
  const props = { ...freeform, width: { ...freeform.width, 'x-resolution-slider-max-pixels': 4194304 } }
  for (const ratio of RATIO_CHOICES) {
    const [w, h] = ratio.split(':').map(Number)
    assert.equal(megapixelSliderBounds(props, w / h).max, 4)
    const r = resolveResolution(fixed(ratio, 4), null, props)
    assert.equal(r.ratioChoice, ratio)
    assert.ok(Math.abs(r.mp - 4) < 0.1)
  }
  const custom = policyWithDims(fixed('1:1', 1), 3072, 2176)
  const r = resolveResolution(custom, null, props)
  assert.deepEqual([r.width, r.height], [3072, 2176])
  assert.ok(r.mp > 4)
  assert.equal(megapixelSliderBounds(props, 3072 / 2176).max, 4)
})

test('the slider hint never caps followed reference dimensions', () => {
  const props = { ...freeform, width: { ...freeform.width, 'x-resolution-slider-max-pixels': 4194304 } }
  const r = resolveResolution(follow(), { width: 4096, height: 2048 }, props)
  assert.deepEqual([r.width, r.height], [4096, 2048])
  assert.equal(r.mp, 8)
  assert.equal(megapixelSliderBounds(props, 2).max, 4)
  const ungridded = resolveResolution(follow(), { width: 1023, height: 1001 }, { width: { maximum: 4096 }, height: { maximum: 4096 } })
  assert.deepEqual([ungridded.width, ungridded.height], [1023, 1001])
  for (const [width, height] of [[64, 64], [8192, 4096]]) {
    const unbounded = resolveResolution(follow(), { width, height }, { width: {}, height: {} })
    assert.deepEqual([unbounded.width, unbounded.height], [width, height])
  }
})

test('older Draw Things descriptors retain their multipleOf grid', () => {
  const props = { width: { minimum: 64, maximum: 4096, multipleOf: 64 }, height: { minimum: 64, maximum: 4096, multipleOf: 64 } }
  const r = resolveResolution(fixed('21:9', 4), null, props)
  assert.deepEqual([r.width, r.height], [3136, 1344])
})

test('Runware retains variable limits and caps area without clipping shape', () => {
  const props = { width: { minimum: 128, maximum: 2048, 'x-step': 16 }, height: { minimum: 128, maximum: 2048, 'x-step': 16 } }
  assert.equal(megapixelSliderBounds(props, 1).max, 4)
  assert.ok(Math.abs(megapixelSliderBounds(props, 21 / 9).max - 12 / 7) < 0.001)
  const p = fixed('21:9', 4)
  const r = resolveResolution(p, null, props)
  assert.equal(r.ratioChoice, '21:9')
  assert.equal(r.width, 2048)
  assert.equal(r.height, 880)
  assert.equal(p.mp, 4)
  assert.equal(resolveResolution({ ...p, ratio: '1:1' }, null, props).mp, 4)
})
