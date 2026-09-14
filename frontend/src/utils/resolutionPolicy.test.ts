import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  resolveResolution,
  defaultResolutionPolicy,
  policyWithDims,
  applyCarriedPolicy,
  carriedPolicy,
  tierGroups,
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
  assert.equal(t2i.mp, 1.049)
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
