import assert from 'node:assert/strict'
import test from 'node:test'

import { updaterFeedConfiguration } from '../src/updaterFeed.ts'

test('generic update feeds use R2-compatible single range requests', () => {
  assert.deepEqual(updaterFeedConfiguration('https://updates.example.test/feed'), {
    provider: 'generic',
    url: 'https://updates.example.test/feed',
    useMultipleRangeRequest: false,
  })
})
