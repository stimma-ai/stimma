import assert from 'node:assert/strict'
import test from 'node:test'
import { pinchCrop, type CropPinchFrame } from '../ported/cropPinch.ts'

const frame: CropPinchFrame = {
  crop: { x: 0.5, y: 0.5, width: 1, height: 1, aspectRatio: 1 },
  zoom: 0.5, width: 1000, height: 1000, rotation: 0, flipX: false, flipY: false,
}
const start: [{x:number;y:number},{x:number;y:number}] = [{ x: -50, y: 0 }, { x: 50, y: 0 }]
test('spreading fingers zooms the image while crop frame stays the same screen size', () => {
  const next = pinchCrop(frame, start, [{ x: -100, y: 0 }, { x: 100, y: 0 }])
  assert.equal(next.zoom, 1)
  assert.equal(next.crop.width, 0.5)
  assert.equal(next.crop.height, 0.5)
  assert.equal(next.crop.x, 0.5)
  assert.equal(next.crop.width * next.zoom, frame.crop.width * frame.zoom)
  assert.equal(next.crop.aspectRatio, 1)
})
test('two-finger translation moves the image with the fingers', () => {
  const next = pinchCrop(frame, start, [{ x: 0, y: 25 }, { x: 100, y: 25 }])
  assert.equal(next.crop.x, 0.4)
  assert.equal(next.crop.y, 0.45)
})
test('twisting rotates the image with the fingers, including mirrored images', () => {
  const angle = Math.PI / 6
  const end: typeof start = [{ x: -50 * Math.cos(angle), y: -50 * Math.sin(angle) }, { x: 50 * Math.cos(angle), y: 50 * Math.sin(angle) }]
  assert.ok(Math.abs(pinchCrop(frame, start, end).crop.rotation! + angle) < 1e-10)
  assert.ok(Math.abs(pinchCrop({ ...frame, flipX: true }, start, end).crop.rotation! - angle) < 1e-10)
})
test('off-center pinch keeps the source point between the fingers anchored', () => {
  const next = pinchCrop(frame, [{ x: 0, y: 0 }, { x: 100, y: 0 }], [{ x: -50, y: 0 }, { x: 150, y: 0 }])
  assert.equal(next.crop.x, 0.55)
  assert.ok(Math.abs((0.6 - next.crop.x) * frame.width * next.zoom - 50) < 1e-10)
})
