import assert from 'node:assert/strict'
import test from 'node:test'
import { nextSpriteFrame, spriteFrameIndices } from './spritePlayback.js'

test('merged holds retain logical frames, including after timing edits', () => {
  const anim = { frameCount: 3, fps: 10, durations: [100, 100, 100] }
  assert.deepEqual(spriteFrameIndices(anim, [200, 100]), [0, 0, 1])
  assert.deepEqual(spriteFrameIndices(anim, [0]), [0, 0, 0])
  assert.deepEqual(spriteFrameIndices({ ...anim, durations: [50, 300, 150], frameIndices: [0, 0, 1] }, [200, 100]), [0, 0, 1])
  assert.throws(() => spriteFrameIndices(anim, [150, 150]), /boundaries/)
  assert.throws(() => spriteFrameIndices({ ...anim, frameIndices: [0, 0, 9] }, [200, 100]), /mapping/)
})

function sequence(mode, looping, first = 0, last = 3) {
  let state = { index: 0, direction: 1, playing: true }
  const indices = [state.index]
  for (let i = 0; i < 9 && state.playing; i++) {
    state = nextSpriteFrame({ ...state, mode, looping, first, last })
    if (state.playing) indices.push(state.index)
  }
  return { indices, playing: state.playing }
}

test('once stops at the final frame; loop repeats only its span', () => {
  assert.deepEqual(sequence('once', false), { indices: [0, 1, 2, 3], playing: false })
  assert.deepEqual(sequence('loop', true, 1).indices, [0, 1, 2, 3, 1, 2, 3, 1, 2, 3])
})

test('pingpong reverses without duplicate endpoints and respects loop start', () => {
  assert.deepEqual(sequence('pingpong', true).indices, [0, 1, 2, 3, 2, 1, 0, 1, 2, 3])
  assert.deepEqual(sequence('pingpong', true, 1).indices, [0, 1, 2, 3, 2, 1, 2, 3, 2, 1])
  assert.deepEqual(sequence('pingpong', false).indices, [0, 1, 2, 3])
  assert.deepEqual(sequence('pingpong', true, 0, 0).indices, Array(10).fill(0))
})
