import assert from 'node:assert/strict'
import test from 'node:test'
import { createScopedSnapshot } from './scopedSnapshot.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function harness() {
  const calls = []
  let clock = 0
  const snapshot = createScopedSnapshot(scope => {
    const d = deferred()
    calls.push({ scope, ...d })
    return d.promise
  }, { now: () => clock })
  return { snapshot, calls, advance: ms => { clock += ms } }
}

test('concurrent and later reads of one scope share a single request', async () => {
  const { snapshot, calls } = harness()
  const a = snapshot.read('s')
  const b = snapshot.read('s')
  assert.equal(calls.length, 1)
  calls[0].resolve({ n: 1 })
  assert.deepEqual(await a, { n: 1 })
  assert.deepEqual(await b, { n: 1 })
  assert.deepEqual(await snapshot.read('s'), { n: 1 })
  assert.equal(calls.length, 1)
})

test('scopes never share values', async () => {
  const { snapshot, calls } = harness()
  const a = snapshot.read('server\nmain')
  const b = snapshot.read('server\nother')
  assert.equal(calls.length, 2)
  calls[0].resolve({ profile: 'main' })
  calls[1].resolve({ profile: 'other' })
  assert.deepEqual(await a, { profile: 'main' })
  assert.deepEqual(await b, { profile: 'other' })
})

test('each caller gets its own copy', async () => {
  const { snapshot, calls } = harness()
  const first = snapshot.read('s')
  calls[0].resolve({ list: [1] })
  ;(await first).list.push(2)
  assert.deepEqual(await snapshot.read('s'), { list: [1] })
})

test('maxAge bounds reuse; refresh always asks and becomes the shared value', async () => {
  const { snapshot, calls, advance } = harness()
  const first = snapshot.read('s')
  calls[0].resolve({ v: 1 })
  await first
  advance(1000)
  assert.deepEqual(await snapshot.read('s', { maxAgeMs: 5000 }), { v: 1 })
  const stale = snapshot.read('s', { maxAgeMs: 500 })
  assert.equal(calls.length, 2)
  calls[1].resolve({ v: 2 })
  assert.deepEqual(await stale, { v: 2 })
  const forced = snapshot.refresh('s')
  assert.equal(calls.length, 3)
  calls[2].resolve({ v: 3 })
  await forced
  assert.deepEqual(snapshot.peek('s'), { v: 3 })
})

test('failures are not stored', async () => {
  const { snapshot, calls } = harness()
  const failed = snapshot.read('s')
  calls[0].reject(new Error('PIN required'))
  await assert.rejects(failed, /PIN required/)
  assert.equal(snapshot.peek('s'), null)
  const retry = snapshot.read('s')
  assert.equal(calls.length, 2)
  calls[1].resolve({ ok: true })
  assert.deepEqual(await retry, { ok: true })
})

test('a request answered after invalidation reaches its caller but is not stored or shared', async () => {
  const { snapshot, calls } = harness()
  const before = snapshot.read('s')
  snapshot.invalidate()
  const after = snapshot.read('s')
  assert.equal(calls.length, 2, 'a reader after invalidation does not join the old request')
  calls[0].resolve({ v: 'before lock' })
  assert.deepEqual(await before, { v: 'before lock' })
  assert.equal(snapshot.peek('s'), null)
  calls[1].resolve({ v: 'after unlock' })
  assert.deepEqual(await after, { v: 'after unlock' })
  assert.deepEqual(snapshot.peek('s'), { v: 'after unlock' })
})

test('an older answer arriving late cannot replace a newer one', async () => {
  const { snapshot, calls } = harness()
  const older = snapshot.read('s')
  const newer = snapshot.refresh('s')
  calls[1].resolve({ v: 'new' })
  await newer
  calls[0].resolve({ v: 'old' })
  await older
  assert.deepEqual(snapshot.peek('s'), { v: 'new' })
})

test('invalidate can keep one scope', async () => {
  const { snapshot, calls } = harness()
  const a = snapshot.read('a')
  const b = snapshot.read('b')
  calls[0].resolve(1)
  calls[1].resolve(2)
  await Promise.all([a, b])
  snapshot.invalidate(scope => scope === 'b')
  assert.equal(snapshot.peek('a'), null)
  assert.equal(snapshot.peek('b'), 2)
  assert.deepEqual(snapshot.scopes(), ['b'])
})

test('the load starts synchronously, under the identity current at the call', () => {
  let identity = 'main'
  const seen = []
  const snapshot = createScopedSnapshot(() => { seen.push(identity); return new Promise(() => {}) })
  snapshot.read('main')
  identity = 'other'
  assert.deepEqual(seen, ['main'])
})

test('an authorization refusal evicts the stored value and fences older requests', async () => {
  const calls = []
  const snapshot = createScopedSnapshot(() => {
    const d = deferred()
    calls.push(d)
    return d.promise
  }, { evictOnError: error => error.status === 403 })
  const first = snapshot.read('s')
  calls[0].resolve({ secret: 1 })
  await first
  const older = snapshot.refresh('s') // started before the refusal, answers after it
  const refused = snapshot.refresh('s')
  const refusal = Object.assign(new Error('PIN required'), { status: 403 })
  calls[2].reject(refusal)
  await assert.rejects(refused, /PIN required/)
  assert.equal(snapshot.peek('s'), null, 'the old value is gone')
  calls[1].resolve({ secret: 2 })
  await older
  assert.equal(snapshot.peek('s'), null, 'an answer from before the refusal is not stored')
  const next = snapshot.read('s')
  assert.equal(calls.length, 4, 'the next reader asks the server')
  calls[3].reject(refusal)
  await assert.rejects(next)
})

test('a request past its bound is aborted and dropped; the next reader starts a new one', async () => {
  const timers = []
  const fakeTimers = { setTimeout: (fn, ms) => timers.push({ fn, ms }) && timers.length, clearTimeout: () => {} }
  const signals = []
  const snapshot = createScopedSnapshot((_scope, signal) => { signals.push(signal); return new Promise(() => {}) },
    { timeoutMs: 5000, timers: fakeTimers })
  const hung = snapshot.read('s')
  const joined = snapshot.read('s')
  assert.equal(signals.length, 1)
  assert.equal(timers[0].ms, 5000)
  timers[0].fn()
  assert.equal(signals[0].aborted, true, 'the shared request itself is aborted')
  await assert.rejects(hung, /timed out/)
  await assert.rejects(joined, /timed out/)
  void snapshot.read('s').catch(() => {})
  assert.equal(signals.length, 2, 'a later reader does not join the abandoned request')
})
