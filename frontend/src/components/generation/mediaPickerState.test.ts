import assert from 'node:assert/strict'
import test from 'node:test'
import { defaultPickerState, mergeUsedBefore, parsePickerState, pickerViewKey } from './mediaPickerState.ts'

test('a stored view comes back, keeping only valid fields', () => {
  const stored = JSON.stringify({
    feed: 'generated',
    markerIds: [1, 'x', 3],
    query: 'jacket',
    searchOpen: true,
    sort: 'nonsense',
    seed: 77,
    scrollTop: 420,
    scrollKey: 'k',
  })
  const state = parsePickerState(stored)!
  assert.equal(state.feed, 'generated')
  assert.deepEqual(state.markerIds, [1, 3])
  assert.equal(state.query, 'jacket')
  assert.equal(state.searchOpen, true)
  assert.equal(state.sort, 'created_desc')
  assert.equal(state.seed, 77)
  assert.equal(state.scrollTop, 420)
})

test('nothing usable stored means a first run', () => {
  assert.equal(parsePickerState(null), null)
  assert.equal(parsePickerState('not json'), null)
  assert.equal(parsePickerState(JSON.stringify({ feed: 'recents' })), null)
})

test('a scroll offset belongs to one list', () => {
  const state = defaultPickerState('all')
  const key = pickerViewKey(state, 'image')
  assert.notEqual(pickerViewKey({ ...state, markerIds: [2] }, 'image'), key)
  assert.notEqual(pickerViewKey({ ...state, query: 'red' }, 'image'), key)
  assert.notEqual(pickerViewKey(state, 'video'), key)
  assert.equal(pickerViewKey({ ...state, markerIds: [3, 1] }, 'image'), pickerViewKey({ ...state, markerIds: [1, 3] }, 'image'))
  // Used before has one order, whatever the sort says.
  const used = defaultPickerState('used')
  assert.equal(pickerViewKey({ ...used, sort: 'random' }, 'image'), pickerViewKey(used, 'image'))
})

test('used before is one entry per media, last used first', () => {
  const merged = mergeUsedBefore(
    [{ mediaId: 1, usedAt: 10 }, { mediaId: 2, usedAt: 50 }],
    [{ mediaId: 1, usedAt: 90 }, { mediaId: 3, usedAt: 20 }],
  )
  assert.deepEqual(merged.map(e => [e.mediaId, e.usedAt]), [[1, 90], [2, 50], [3, 20]])
})
