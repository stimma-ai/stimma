import assert from 'node:assert/strict'
import test from 'node:test'
import { createScopedLoad, scopeKey } from './scopedLoad.ts'

function deferred() {
  let resolve!: (value?: unknown) => void
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('scope keys distinguish server, profile and project', () => {
  assert.notEqual(scopeKey('a', 'p1', null), scopeKey('a', 'p1', 1))
  assert.notEqual(scopeKey('a', 'p1', 1), scopeKey('a', 'p2', 1))
  assert.notEqual(scopeKey('a', 'p1', 1), scopeKey('b', 'p1', 1))
  assert.equal(scopeKey('a', undefined, null), scopeKey('a', null, null))
})

test('concurrent requests for one scope share a single load', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const gate = deferred()
  let calls = 0
  const load = async () => { calls++; await gate.promise }
  const first = loads.request('a', load)
  const second = loads.request('a', load)
  gate.resolve()
  await Promise.all([first, second])
  assert.equal(calls, 1)
})

test('a fresh load is reused until it expires or is invalidated', async () => {
  let clock = 0
  const loads = createScopedLoad({ freshMs: 1000, now: () => clock })
  let calls = 0
  const load = async () => { calls++ }
  await loads.request('a', load)
  assert.equal(await loads.request('a', load), false)
  assert.equal(calls, 1)
  clock = 1500
  await loads.request('a', load)
  assert.equal(calls, 2)
  loads.invalidate()
  await loads.request('a', load)
  assert.equal(calls, 3)
  await loads.request('a', load, { force: true })
  assert.equal(calls, 4)
})

test('a change during a load leaves the result stale', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const gate = deferred()
  let calls = 0
  const pending = loads.request('a', async () => { calls++; await gate.promise })
  loads.invalidate()
  gate.resolve()
  await pending
  await loads.request('a', async () => { calls++ })
  assert.equal(calls, 2)
})

test('failed loads are not treated as fresh', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  let calls = 0
  await loads.request('a', async () => { calls++; return false })
  await loads.request('a', async () => { calls++ })
  assert.equal(calls, 2)
})

test('a newer scope makes the older load obsolete', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const gate = deferred()
  const shown: string[] = []
  const old = loads.request('a', async isCurrent => { await gate.promise; if (isCurrent()) shown.push('a') })
  await loads.request('b', async isCurrent => { if (isCurrent()) shown.push('b') })
  const partial = loads.guard()
  gate.resolve()
  await old
  assert.deepEqual(shown, ['b'])
  assert.equal(loads.activeKey, 'b')
  assert.equal(partial(), true)
  // The obsolete scope never became fresh, so returning to it loads again.
  let calls = 0
  await loads.request('a', async () => { calls++ })
  assert.equal(calls, 1)
  assert.equal(partial(), false)
})

test('a slow load is joined by every later request and its result is used', async () => {
  let clock = 0
  const loads = createScopedLoad({ freshMs: 1000, now: () => clock })
  const slow = deferred()
  const shown: string[] = []
  let calls = 0
  const load = async (isCurrent: () => boolean) => { calls++; await slow.promise; if (isCurrent()) shown.push('slow') }
  const first = loads.request('a', load)
  // Repeated visits long after it started still wait for the same read.
  for (const at of [16_000, 32_000, 60_000]) {
    clock = at
    assert.equal(loads.request('a', load), first)
  }
  slow.resolve()
  await first
  assert.equal(calls, 1)
  assert.deepEqual(shown, ['slow'])
  assert.equal(await loads.request('a', load), false)
})

test('a forced retry does not throw away the first reply for the same scope', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const slow = deferred()
  const retry = deferred()
  const shown: string[] = []
  const first = loads.request('a', async isCurrent => { await slow.promise; if (isCurrent()) shown.push('first') })
  const second = loads.request('a', async isCurrent => { await retry.promise; if (isCurrent()) shown.push('retry') }, { force: true })
  slow.resolve()
  await first
  assert.deepEqual(shown, ['first'])
  retry.resolve()
  await second
  assert.deepEqual(shown, ['first', 'retry'])
})
