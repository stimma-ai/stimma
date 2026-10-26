import assert from 'node:assert/strict'
import test from 'node:test'
import { reconcileChatItems } from './chatReconcile.ts'

type Item = { id: number, item_type: string, message_text?: string, item_metadata?: Record<string, unknown> }

const item = (id: number, extra: Partial<Item> = {}): Item => ({ id, item_type: 'assistant_message', message_text: `m${id}`, ...extra })
const snapshot = (items: Item[]) => new Map(items.map(i => [i.id, i]))

test('an item changed while away is replaced even though its ID is unchanged', () => {
  const running = item(3, { item_type: 'tool_call', item_metadata: { status: 'running' } })
  const current = [item(1), item(2), running]
  const done = { ...running, message_text: 'finished', item_metadata: { status: 'completed' } }
  const { items, changed } = reconcileChatItems(current, [item(1), item(2), done], { hasMore: false, before: snapshot(current) })
  assert.equal(changed, true)
  assert.deepEqual(items[2], done)
  // Unchanged items keep their identity so the view does not re-render them.
  assert.equal(items[0], current[0])
  assert.equal(items[1], current[1])
})

test('identical content leaves the transcript array untouched', () => {
  const current = [item(1), item(2)]
  const result = reconcileChatItems(current, [item(1), item(2)], { hasMore: false, before: snapshot(current) })
  assert.equal(result.changed, false)
  assert.equal(result.items, current)
})

test('items deleted inside the returned window are removed, missed items are inserted', () => {
  const current = [item(10), item(11), item(12), item(13)]
  const fresh = [item(10), item(12), item(14)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: true, before: snapshot(current) })
  assert.deepEqual(items.map(i => i.id), [10, 12, 14])
})

test('a deleted newest item is removed even though it is past the snapshot', () => {
  const current = [item(1), item(2), item(3)]
  const { items } = reconcileChatItems(current, [item(1), item(2)], { hasMore: false, before: snapshot(current) })
  assert.deepEqual(items.map(i => i.id), [1, 2])
})

test('older history outside the snapshot window is kept', () => {
  // Pages 1..4 were loaded by scrolling up; the snapshot covers 5..7 only.
  const current = [item(1), item(2), item(3), item(4), item(5), item(6), item(7)]
  const fresh = [item(5), item(6, { message_text: 'edited' }), item(7)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: true, before: snapshot(current) })
  assert.deepEqual(items.map(i => i.id), [1, 2, 3, 4, 5, 6, 7])
  assert.equal(items[5].message_text, 'edited')
  assert.equal(items[0], current[0])
})

test('a complete snapshot removes anything it does not contain', () => {
  const current = [item(1), item(2)]
  const { items } = reconcileChatItems(current, [], { hasMore: false, before: snapshot(current) })
  assert.deepEqual(items, [])
})

test('an empty partial snapshot proves nothing', () => {
  const current = [item(1), item(2)]
  const result = reconcileChatItems(current, [], { hasMore: true, before: snapshot(current) })
  assert.equal(result.items, current)
})

test('live updates that land while the fetch is in flight win over the snapshot', () => {
  const before = [item(1), item(2), item(3), item(4)]
  // During the fetch: item 2 was updated live, item 3 was deleted live, and
  // the just-sent user message 6 arrived. The snapshot predates all of that.
  const liveUpdate = item(2, { message_text: 'newer than snapshot' })
  const sent = item(6, { item_type: 'user_message', message_text: 'hello' })
  const current = [before[0], liveUpdate, before[3], sent]
  const fresh = [item(1), item(2, { message_text: 'older' }), item(3), item(4), item(5)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: false, before: snapshot(before) })
  assert.deepEqual(items.map(i => i.id), [1, 2, 4, 5, 6])
  assert.equal(items[1], liveUpdate)
  assert.equal(items[4], sent)
})
