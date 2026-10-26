// The chat's media collector agrees with the server's media filter
// (GET items?only=media) on shared vectors. The backend's
// tests/test_chat_media_parity.py checks the same vectors' served forms and
// that the filter returns a record exactly when media_ids is non-empty.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { collectChatMedia } from '../src/utils/chatMedia.js'

const { vectors } = JSON.parse(readFileSync(new URL('./fixtures/chatMediaVectors.json', import.meta.url), 'utf8'))

for (const vector of vectors) {
  test(`collector on served item: ${vector.name}`, () => {
    const served = {
      id: 1,
      item_type: vector.record.item_type,
      message_text: vector.record.message_text,
      item_metadata: vector.served_metadata,
      parent_item_id: vector.delegated ? 99 : null,
    }
    assert.deepEqual(collectChatMedia([served]).map(entry => entry.id), vector.media_ids)
  })
}
