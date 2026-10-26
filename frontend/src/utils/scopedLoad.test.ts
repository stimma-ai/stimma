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

test('forced requests during a read coalesce into one rerun after it', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const slow = deferred()
  const order: string[] = []
  let running = 0
  let maxRunning = 0
  const load = (name: string, gate?: Promise<unknown>) => async () => {
    running++
    maxRunning = Math.max(maxRunning, running)
    order.push(`start ${name}`)
    await gate
    order.push(`end ${name}`)
    running--
  }
  const first = loads.request('a', load('first', slow.promise))
  const forced = [
    loads.request('a', load('retry 1'), { force: true }),
    loads.request('a', load('retry 2'), { force: true }),
  ]
  // A plain request now joins the pending rerun rather than starting a third read.
  const joined = loads.request('a', load('visit'))
  assert.deepEqual(order, ['start first'])
  slow.resolve()
  await first
  await Promise.all([...forced, joined])
  assert.deepEqual(order, ['start first', 'end first', 'start retry 2', 'end retry 2'])
  assert.equal(maxRunning, 1)
  assert.equal(await loads.request('a', load('later')), false)
})

test('a request after an invalidation during a read reruns once it settles', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const slow = deferred()
  let calls = 0
  const first = loads.request('a', async () => { calls++; await slow.promise })
  loads.invalidate()
  const visit = loads.request('a', async () => { calls++ })
  assert.equal(calls, 1)
  slow.resolve()
  await first
  await visit
  assert.equal(calls, 2)
  assert.equal(await loads.request('a', async () => { calls++ }), false)
})

test('a scope change cancels a pending rerun', async () => {
  const loads = createScopedLoad({ freshMs: 1000 })
  const slow = deferred()
  const ran: string[] = []
  void loads.request('a', async () => { await slow.promise })
  const rerun = loads.request('a', async () => { ran.push('a rerun') }, { force: true })
  await loads.request('b', async () => { ran.push('b') })
  slow.resolve()
  await rerun
  assert.deepEqual(ran, ['b'])
})
