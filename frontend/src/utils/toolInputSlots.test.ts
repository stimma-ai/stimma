import assert from 'node:assert/strict'
import test from 'node:test'
import { filledSlots, mergeSlotItems, toolDropSlot } from './toolInputSlots.ts'

test('replacing one slot keeps the other items, prep and all', () => {
  const first = { mediaId: 1, _crop: { x: 0, y: 0, width: 0.5, height: 1 } }
  const second = { mediaId: 2, _scale: { mode: 'factor', factor: 0.75 } }
  const merged = mergeSlotItems<any>([first, second], [{ mediaId: 9 }], { replaceIndex: 0, max: 4 })
  assert.deepEqual(merged.map(item => item.mediaId), [9, 2])
  assert.equal(merged[1], second, 'the untouched slot is the same object')

  const second2 = mergeSlotItems<any>([first, second], [{ mediaId: 9 }, { mediaId: 10 }], { replaceIndex: 1, max: 4 })
  assert.deepEqual(second2.map(item => item.mediaId), [1, 9])
  assert.equal(second2[0], first)
})

test('a replace index past the end appends while there is room', () => {
  assert.deepEqual(mergeSlotItems([1], [5], { replaceIndex: 3, max: 3 }), [1, 5])
  assert.deepEqual(mergeSlotItems([1, 2, 3], [5], { replaceIndex: 3, max: 3 }), [1, 2, 3])
})

test('add appends within capacity; a plain send replaces everything', () => {
  assert.deepEqual(mergeSlotItems([1, 2], [3, 4, 5], { append: true, max: 4 }), [1, 2, 3, 4])
  assert.deepEqual(mergeSlotItems([1, 2], [3], { append: true, max: 1 }), [3])
  assert.deepEqual(mergeSlotItems([1, 2], [3, 4], { max: Infinity }), [3, 4])
  assert.deepEqual(mergeSlotItems([1, 2], [3, 4], { max: 1 }), [3])
})

test('a tool drop goes to the slot send-to-tool fills', () => {
  const edit = { task_type: 'image-to-image', parameter_schema: { properties: { input_images: { type: 'array', 'x-max-items': 3 } } } }
  assert.deepEqual(toolDropSlot(edit, 'image'), { field: 'inputImages', max: 3 })
  const avatar = {
    task_type: 'image-to-video',
    parameter_schema: { properties: { input_images: { type: 'array', 'x-max-items': 1 }, input_audios: { type: 'array', maxItems: 2 } } },
  }
  assert.deepEqual(toolDropSlot(avatar, 'audio'), { field: 'inputAudios', max: 2 })
  const i2v = { task_type: 'image-to-video', parameter_schema: { properties: { input_images: { type: 'array', 'x-control': 'video_frame_picker' } } } }
  assert.deepEqual(toolDropSlot(i2v, 'image'), { field: 'frames', max: 2 })
  const outline = { task_type: 'upscale-image', parameter_outline: { properties: { input_image: { type: 'string' } } } }
  assert.deepEqual(toolDropSlot(outline, 'image'), { field: 'inputImages', max: 1 })
  assert.equal(toolDropSlot({ task_type: 'text-to-image', parameter_schema: { properties: {} } }, 'image'), null)
})

test('filled slots come from the saved tool state', () => {
  const state = {
    inputImages: [
      { mediaId: 4, hash: 'a' },
      { path: '/frames/x.png', _videoSource: { mediaId: 8, hash: 'v' } },
      { path: '/uploads/y.png' },
    ],
  }
  assert.deepEqual(filledSlots('inputImages', state), [{ mediaId: 4, hash: 'a' }, { mediaId: 8, hash: 'v' }, {}])
  assert.equal(filledSlots('inputImages', null), null)
  assert.equal(filledSlots('inputImages', { batchMode: true, inputImages: [{ mediaId: 1 }] }), null)
  assert.deepEqual(filledSlots('frames', {}, { startImage: { mediaId: 1 }, endImage: null }), [{ mediaId: 1, hash: undefined }])
})
