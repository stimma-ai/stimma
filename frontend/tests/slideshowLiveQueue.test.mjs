import assert from 'node:assert/strict'
import test from 'node:test'

import {
  diffInsertedLiveIds,
  orderLiveAdvanceCandidates,
  orderLiveAdvanceKeys,
  shouldQueueLiveArrival
} from '../src/utils/slideshowLiveQueue.js'

test('diffInsertedLiveIds reports provider-order inserts', () => {
  assert.deepEqual(
    diffInsertedLiveIds(['c', 'b', 'a'], ['a']),
    [
      { key: 'c', index: 0 },
      { key: 'b', index: 1 }
    ]
  )
})

test('live arrivals drain from displayed item toward newest during burst flushes', () => {
  const arrivals = diffInsertedLiveIds(['c', 'b', 'a'], ['a'])
  let currentIndex = 0
  const candidates = []

  for (const arrival of arrivals) {
    if (shouldQueueLiveArrival({
      currentIndex,
      insertIndex: arrival.index,
      followStream: true,
      randomized: false
    })) {
      candidates.push(arrival)
    }
    if (currentIndex >= arrival.index) currentIndex += 1
  }

  assert.equal(currentIndex, 2)
  assert.deepEqual(orderLiveAdvanceCandidates(candidates).map(item => item.key), ['b', 'c'])
})

test('parked older images pin position but do not queue live advances', () => {
  assert.equal(shouldQueueLiveArrival({
    currentIndex: 4,
    insertIndex: 0,
    followStream: false,
    randomized: false
  }), false)
})

test('existing backlog is re-sorted when a later insert lands between queued items', () => {
  assert.deepEqual(
    orderLiveAdvanceKeys(['c', 'b'], ['c', 'b', 'a']),
    ['b', 'c']
  )
})

test('stale or duplicate queued keys are removed during provider-order sorting', () => {
  assert.deepEqual(
    orderLiveAdvanceKeys(['c', 'missing', 'c', 'b'], ['c', 'b', 'a']),
    ['b', 'c']
  )
})
