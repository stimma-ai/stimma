import assert from 'node:assert/strict'
import test from 'node:test'
import { withReadDeadline } from './readDeadline.ts'

test('a read that outlives its deadline is aborted', async () => {
  let seen: AbortSignal | null = null
  await assert.rejects(withReadDeadline(signal => {
    seen = signal
    return new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))))
  }, 20))
  assert.equal(seen!.aborted, true)
})

test('settling early, either way, aborts whatever the read left running', async () => {
  let left: AbortSignal | null = null
  assert.equal(await withReadDeadline(async signal => { left = signal; return 'done' }, 10_000), 'done')
  assert.equal(left!.aborted, true)
  await assert.rejects(withReadDeadline(async signal => { left = signal; throw new Error('503') }, 10_000))
  assert.equal(left!.aborted, true)
})
