import assert from 'node:assert/strict'
import test from 'node:test'
import { sharedRead } from '../src/utils/sharedRead.js'

test('consumers refreshing on the same reconnect share one read; a later read goes to the network', async () => {
  let reads = 0
  let finish
  const read = () => { reads++; return new Promise(resolve => { finish = resolve }) }
  const strips = [sharedRead('jobs:p1', read), sharedRead('jobs:p1', read), sharedRead('jobs:p1', read)]
  const otherProfile = sharedRead('jobs:p2', () => { reads++; return 'other' })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(reads, 2)
  finish('snapshot')
  assert.deepEqual(await Promise.all(strips), ['snapshot', 'snapshot', 'snapshot'])
  assert.equal(await otherProfile, 'other')
  await sharedRead('jobs:p1', () => { reads++; return 'fresh' })
  assert.equal(reads, 3, 'nothing is cached after the read settles')
  await assert.rejects(sharedRead('jobs:p1', () => { throw new Error('offline') }), /offline/)
  assert.equal(await sharedRead('jobs:p1', () => 'retried'), 'retried', 'a failure is not remembered')
})
