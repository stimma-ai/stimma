import assert from 'node:assert/strict'
import test from 'node:test'
import { reconcileChatItems, sameChatItem } from './chatReconcile.ts'

type Item = { id: number, item_type: string, message_text?: string, item_metadata?: Record<string, unknown> | null }

const item = (id: number, extra: Partial<Item> = {}): Item => ({ id, item_type: 'assistant_message', message_text: `m${id}`, item_metadata: null, ...extra })
const ids = (items: Item[]) => new Set(items.map(i => i.id))
const quiet = () => new Map<number, Item | null>()
const newest = (items: Item[]) => items.length ? items[items.length - 1].id : Number.NEGATIVE_INFINITY

test('an item changed while away is replaced even though its ID is unchanged', () => {
  const running = item(3, { item_type: 'tool_call', item_metadata: { status: 'running' } })
  const current = [item(1), item(2), running]
  const done = { ...running, message_text: 'finished', item_metadata: { status: 'completed' } }
  const { items, changed } = reconcileChatItems(current, [item(1), item(2), done], { hasMore: false, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.equal(changed, true)
  assert.deepEqual(items[2], done)
  // Unchanged items keep their identity so the view does not re-render them.
  assert.equal(items[0], current[0])
  assert.equal(items[1], current[1])
})

test('identical content leaves the transcript array untouched', () => {
  const current = [item(1, { item_metadata: { a: [1, 2] } }), item(2)]
  const fresh = [item(1, { item_metadata: { a: [1, 2] } }), item(2)]
  const result = reconcileChatItems(current, fresh, { hasMore: false, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.equal(result.changed, false)
  assert.equal(result.items, current)
})

test('items deleted inside the returned window are removed, missed items are inserted', () => {
  const current = [item(10), item(11), item(12), item(13)]
  const fresh = [item(10), item(12), item(14)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: true, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.deepEqual(items.map(i => i.id), [10, 12, 14])
})

test('a deleted newest item is removed even though it is past the snapshot', () => {
  const current = [item(1), item(2), item(3)]
  const { items } = reconcileChatItems(current, [item(1), item(2)], { hasMore: false, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.deepEqual(items.map(i => i.id), [1, 2])
})

test('older history outside the snapshot window is kept', () => {
  // Pages 1..4 were loaded by scrolling up; the snapshot covers 5..7 only.
  const current = [item(1), item(2), item(3), item(4), item(5), item(6), item(7)]
  const fresh = [item(5), item(6, { message_text: 'edited' }), item(7)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: true, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.deepEqual(items.map(i => i.id), [1, 2, 3, 4, 5, 6, 7])
  assert.equal(items[5].message_text, 'edited')
  assert.equal(items[0], current[0])
})

test('loaded history that never reaches a partial snapshot is replaced, not left behind a hole', () => {
  // Items 1..3 were loaded; the chat grew to 1..1200 and the snapshot is 601..1200.
  const current = [item(1), item(2), item(3)]
  const fresh = Array.from({ length: 600 }, (_, i) => item(i + 601))
  const { items, changed } = reconcileChatItems(current, fresh, { hasMore: true, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.equal(changed, true)
  assert.equal(items[0].id, 601)
  assert.equal(items.length, 600)
})

test('loaded history that overlaps a partial snapshot keeps its older part', () => {
  const current = [item(1), item(2), item(3), item(4)]
  const { items } = reconcileChatItems(current, [item(4), item(5)], { hasMore: true, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.deepEqual(items.map(i => i.id), [1, 2, 3, 4, 5])
})

test('a live append past covered history does not count as continuity', () => {
  // 1..3 came from the server; 400 arrived live. Coverage still ends at 3,
  // so a snapshot of 201..400 is disjoint and replaces the older run.
  const current = [item(1), item(2), item(3), item(400)]
  const fresh = Array.from({ length: 200 }, (_, i) => item(i + 201))
  const result = reconcileChatItems(current, fresh, { hasMore: true, before: ids(current), coveredThrough: 3, journal: quiet() })
  assert.equal(result.items[0].id, 201)
  assert.equal(result.items.length, 200)
  assert.equal(result.olderSurvives, false)
  assert.equal(result.coveredThrough, 400)
})

test('a live delete of the snapshot\'s first item still exposes older pages', () => {
  const current = [item(1), item(2), item(3)]
  const fresh = Array.from({ length: 200 }, (_, i) => item(i + 201))
  const journal = new Map<number, Item | null>([[201, null]])
  const result = reconcileChatItems(current, fresh, { hasMore: true, before: ids(current), coveredThrough: 3, journal })
  assert.equal(result.items[0].id, 202)
  assert.equal(result.olderSurvives, false)
})

test('coverage advances through an overlapping snapshot and older history survives', () => {
  const current = [item(1), item(2), item(3), item(4)]
  const result = reconcileChatItems(current, [item(3), item(4), item(5)], { hasMore: true, before: ids(current), coveredThrough: 4, journal: quiet() })
  assert.equal(result.coveredThrough, 5)
  assert.equal(result.olderSurvives, true)
})

test('a complete snapshot removes anything it does not contain', () => {
  const current = [item(1), item(2)]
  const { items } = reconcileChatItems(current, [], { hasMore: false, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.deepEqual(items, [])
})

test('an empty partial snapshot proves nothing', () => {
  const current = [item(1), item(2)]
  const result = reconcileChatItems(current, [], { hasMore: true, before: ids(current), coveredThrough: newest(current), journal: quiet() })
  assert.equal(result.items, current)
})

test('live updates that land while the fetch is in flight win over the snapshot', () => {
  const before = [item(1), item(2), item(3), item(4)]
  // During the fetch: item 2 was updated live, item 3 was deleted live, and
  // the just-sent user message 6 arrived. The snapshot predates all of that.
  const liveUpdate = item(2, { message_text: 'newer than snapshot' })
  const sent = item(6, { item_type: 'user_message', message_text: 'hello' })
  const journal = new Map<number, Item | null>([[2, liveUpdate], [3, null], [6, sent]])
  const current = [before[0], liveUpdate, before[3], sent]
  const fresh = [item(1), item(2, { message_text: 'older' }), item(3), item(4), item(5)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: false, before: ids(before), coveredThrough: newest(before), journal })
  assert.deepEqual(items.map(i => i.id), [1, 2, 4, 5, 6])
  assert.equal(items[1], liveUpdate)
  assert.equal(items[4], sent)
})

test('live changes to items the transcript never loaded beat the snapshot', () => {
  // Items 3 and 4 were created during the disconnect, so the transcript has
  // never seen them. While the fetch is in flight, 3 is updated and 4 deleted
  // live; both handlers find nothing to change locally.
  const current = [item(1), item(2)]
  const updated3 = item(3, { message_text: 'completed live' })
  const journal = new Map<number, Item | null>([[3, updated3], [4, null]])
  const fresh = [item(1), item(2), item(3, { message_text: 'stale' }), item(4)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: false, before: ids(current), coveredThrough: newest(current), journal })
  assert.deepEqual(items.map(i => i.id), [1, 2, 3])
  assert.equal(items[2], updated3)
})

test('object identity is irrelevant: copies of unchanged items still accept offline edits', () => {
  // A live delete filtered the reactive array, which can hand back different
  // wrapper objects for the surviving items. Only the journal marks changes.
  const original = [item(1), item(2), item(3)]
  const current = [{ ...original[0] }, { ...original[1] }]
  const journal = new Map<number, Item | null>([[3, null]])
  const fresh = [item(1), item(2, { message_text: 'edited offline' }), item(3)]
  const { items } = reconcileChatItems(current, fresh, { hasMore: false, before: ids(original), coveredThrough: newest(original), journal })
  assert.deepEqual(items.map(i => i.id), [1, 2])
  assert.equal(items[1].message_text, 'edited offline')
})

test('sameChatItem compares nested values and exits on the first difference', () => {
  assert.equal(sameChatItem(item(1, { item_metadata: { a: { b: 1 } } }), item(1, { item_metadata: { a: { b: 1 } } })), true)
  assert.equal(sameChatItem(item(1, { item_metadata: { a: { b: 1 } } }), item(1, { item_metadata: { a: { b: 2 } } })), false)
  assert.equal(sameChatItem(item(1, { item_metadata: null }), item(1, { item_metadata: {} })), false)
  assert.equal(sameChatItem(item(1), { ...item(1), extra: 1 }), false)
})
