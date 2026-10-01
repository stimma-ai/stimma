import assert from 'node:assert/strict'
import test from 'node:test'

import {
  IDENTITY,
  applyToPoint,
  coTransform,
  cropAffine,
  invert,
  isIdentity,
  multiply,
} from './geometryTransform.ts'
import type { Affine } from './geometryTransform.ts'

const close = (a: number, b: number, epsilon = 1e-6) => Math.abs(a - b) < epsilon

function assertPoint(actual: [number, number], expected: [number, number], message: string) {
  assert.ok(
    close(actual[0], expected[0], 1e-4) && close(actual[1], expected[1], 1e-4),
    `${message}: got [${actual}], expected [${expected}]`
  )
}

test('an identity crop is the identity transform', () => {
  const { matrix, width, height } = cropAffine(
    { rect: { x: 0.5, y: 0.5, width: 1, height: 1 } }, 200, 100
  )
  assert.ok(isIdentity(matrix), `expected identity, got ${matrix}`)
  assert.deepEqual([width, height], [200, 100])
})

test('a centred crop maps its window onto the output frame', () => {
  // A half-size crop centred on the image: the window's top-left (50, 25)
  // becomes the output's origin.
  const { matrix, width, height } = cropAffine(
    { rect: { x: 0.5, y: 0.5, width: 0.5, height: 0.5 } }, 200, 100
  )
  assert.deepEqual([width, height], [100, 50])
  assertPoint(applyToPoint(matrix, 50, 25), [0, 0], 'crop top-left')
  assertPoint(applyToPoint(matrix, 150, 75), [100, 50], 'crop bottom-right')
  assertPoint(applyToPoint(matrix, 100, 50), [50, 25], 'crop centre')
})

test('an off-centre crop follows its centre', () => {
  const { matrix } = cropAffine(
    { rect: { x: 0.25, y: 0.5, width: 0.5, height: 1 } }, 200, 100
  )
  // Window spans x 0..100; its top-left maps to the origin.
  assertPoint(applyToPoint(matrix, 0, 0), [0, 0], 'window origin')
  assertPoint(applyToPoint(matrix, 100, 100), [100, 100], 'window far corner')
})

test('a horizontal flip mirrors across the frame', () => {
  const { matrix, width } = cropAffine(
    { rect: { x: 0.5, y: 0.5, width: 1, height: 1 }, flipX: true }, 200, 100
  )
  assertPoint(applyToPoint(matrix, 0, 50), [width, 50], 'left edge goes right')
  assertPoint(applyToPoint(matrix, 200, 50), [0, 50], 'right edge goes left')
})

test('a quarter turn rotates about the frame centre', () => {
  const { matrix, width, height } = cropAffine(
    { rect: { x: 0.5, y: 0.5, width: 1, height: 1 }, rotation90: 1 }, 100, 100
  )
  assert.deepEqual([width, height], [100, 100])
  // 90° clockwise about the centre: the top-left corner lands top-right.
  assertPoint(applyToPoint(matrix, 0, 0), [100, 0], 'top-left → top-right')
  assertPoint(applyToPoint(matrix, 100, 0), [100, 100], 'top-right → bottom-right')
})

test('matrix inversion round-trips a point', () => {
  const { matrix } = cropAffine(
    { rect: { x: 0.4, y: 0.6, width: 0.7, height: 0.8 }, rotation: 0.2, flipY: true },
    320, 240
  )
  const inverse = invert(matrix)!
  const moved = applyToPoint(matrix, 123, 87)
  assertPoint(applyToPoint(inverse, moved[0], moved[1]), [123, 87], 'round-trip')
})

test('a degenerate matrix reports rather than producing nonsense', () => {
  assert.equal(invert([0, 0, 0, 0, 0, 0] as Affine), null)
})

test('co-transform carries a payload from its old space into the new one', () => {
  const oldGeometry = cropAffine({ rect: { x: 0.5, y: 0.5, width: 1, height: 1 } }, 200, 100)
  const newGeometry = cropAffine({ rect: { x: 0.5, y: 0.5, width: 0.5, height: 0.5 } }, 200, 100)

  const matrix = coTransform(oldGeometry.matrix, newGeometry.matrix)!
  // A mark at the image centre must stay at the centre of the cropped frame.
  assertPoint(applyToPoint(matrix, 100, 50), [50, 25], 'centre stays centred')
  // A mark outside the crop window lands outside the new frame.
  const outside = applyToPoint(matrix, 10, 10)
  assert.ok(outside[0] < 0 && outside[1] < 0, `expected outside the frame, got ${outside}`)
})

test('co-transforming back and forth is lossless in the matrix', () => {
  const a = cropAffine({ rect: { x: 0.45, y: 0.55, width: 0.6, height: 0.7 } }, 400, 300)
  const b = cropAffine({ rect: { x: 0.5, y: 0.5, width: 1, height: 1 } }, 400, 300)

  const forward = coTransform(b.matrix, a.matrix)!
  const back = coTransform(a.matrix, b.matrix)!
  assert.ok(isIdentity(multiply(back, forward), 1e-6), 'un-crop undoes the crop exactly')
})

test('composition is associative in the order the compositor uses', () => {
  const first = cropAffine({ rect: { x: 0.5, y: 0.5, width: 0.8, height: 0.8 } }, 400, 400)
  const second = cropAffine({ rect: { x: 0.5, y: 0.5, width: 0.5, height: 0.5 } }, first.width, first.height)
  const composed = multiply(second.matrix, first.matrix)

  const viaComposed = applyToPoint(composed, 200, 200)
  const stepwise = applyToPoint(first.matrix, 200, 200)
  const viaSteps = applyToPoint(second.matrix, stepwise[0], stepwise[1])
  assertPoint(viaComposed, viaSteps, 'stacked crops compose')
})

test('identity multiplication is neutral', () => {
  const { matrix } = cropAffine({ rect: { x: 0.3, y: 0.7, width: 0.5, height: 0.5 } }, 100, 100)
  assert.deepEqual(multiply(matrix, IDENTITY), matrix)
  assert.deepEqual(multiply(IDENTITY, matrix), matrix)
})

test('quarter turns preserve a rectangular crop without stretching its geometry', () => {
  for (const rotation90 of [1, 3] as const) {
    for (const cropRotation of [0, 0.2]) {
      const { matrix, width, height } = cropAffine({
        rect: { x: 0.4, y: 0.6, width: 0.5, height: 0.5 }, rotation90, cropRotation,
      }, 400, 200)
      assert.deepEqual([width, height], [100, 200])
      assertPoint(applyToPoint(matrix, 160, 120), [50, 100], 'crop centre')
      assert.ok(close(Math.hypot(matrix[0], matrix[1]), 1), 'horizontal pixels retain size')
      assert.ok(close(Math.hypot(matrix[2], matrix[3]), 1), 'vertical pixels retain size')
    }
  }
})
