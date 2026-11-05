import assert from 'node:assert/strict'
import test from 'node:test'
import { planShards, selectShard } from '../scripts/testShards.mjs'

test('shards cover every file exactly once, including newly added files', () => {
  const files = ['long', 'medium', 'short', 'new-test']
  const durations = { long: 100, medium: 70, short: 30 }
  const shards = planShards(files, durations, 2)
  assert.deepEqual(shards.flat().sort(), files.sort())
  assert.equal(new Set(shards.flat()).size, files.length)
  assert.deepEqual(planShards([...files].reverse(), durations, 2), shards)
  const times = shards.map(shard => shard.reduce((sum, file) => sum + (durations[file] ?? 20), 0))
  assert.ok(Math.max(...times) <= 120, `balanced durations: ${times}`)
})

test('invalid or empty shard selections fail instead of silently omitting tests', () => {
  for (const shard of ['0/3', '4/3', '1/0', '1/1000', 'bad', '2/2']) {
    assert.throws(() => selectShard(['one'], {}, shard))
  }
  assert.deepEqual(selectShard(['one', 'two'], {}, '1/2'), ['one'])
})
