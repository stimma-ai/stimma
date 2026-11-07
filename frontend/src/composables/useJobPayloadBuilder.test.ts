import assert from 'node:assert/strict'
import test from 'node:test'

import { lineageMediaId } from './useJobPayloadBuilder.ts'

// Tool View's prompt preparation keys its program by the inputs' library ids with this
// same lookup, so it must agree with a run for a frame grabbed from a library video.
test('a grabbed video frame stands for its source video', () => {
  assert.equal(lineageMediaId({ mediaId: 7 }), 7)
  assert.equal(lineageMediaId({ _videoSource: { mediaId: 42 } }), 42)
  assert.equal(lineageMediaId({ mediaId: 7, _videoSource: { mediaId: 42 } }), 7)
  assert.equal(lineageMediaId({}), undefined)
})
