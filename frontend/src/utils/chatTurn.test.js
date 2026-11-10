import assert from 'node:assert/strict'
import test from 'node:test'

import { lastSentMediaIds, turnEndedWithReply, turnOutputMediaIds } from './chatTurn.js'

const user = (id, attachments = []) => ({ id, item_type: 'user_message', message_text: 'go', item_metadata: { attachments } })
const media = (id, rows) => ({ id, item_type: 'media_display', item_metadata: { display_data: { rows } } })
const reply = (id, text) => ({ id, item_type: 'assistant_message', message_text: text })
const progress = (id, previews) => ({ id, item_type: 'progress_display', item_metadata: { display_data: { status: 'completed', previews } } })

test('the turn made only what came after the last message, outputs only', () => {
  const items = [
    user(1),
    media(2, [{ output: { media_id: 10 } }]),
    user(3, [{ media_id: 20 }]),
    progress(4, [30, 31]),
    media(5, [{ input: { input_image: { media_id: 20 } }, output: { media_id: 30 } }, { output: { media_id: 32 } }]),
  ]
  assert.deepEqual(turnOutputMediaIds(items), [30, 31, 32])
})

test('a turn of words alone made nothing', () => {
  assert.deepEqual(turnOutputMediaIds([user(1), reply(2, 'This one is strongest.')]), [])
})

test('a turn ends in words when its last assistant message has visible text', () => {
  assert.equal(turnEndedWithReply([user(1), reply(2, 'The third one.')]), true)
  assert.equal(turnEndedWithReply([user(1), reply(2, '<think>hmm</think>')]), false)
  assert.equal(turnEndedWithReply([reply(0, 'Old reply'), user(1), progress(2, [5])]), false)
})

test('what was sent is the last message\'s attachments', () => {
  assert.deepEqual(lastSentMediaIds([user(1, [{ media_id: 4 }]), user(2, [{ media_id: 7 }, { path: 'x' }])]), [7])
  assert.deepEqual(lastSentMediaIds([]), [])
})
