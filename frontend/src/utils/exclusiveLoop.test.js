import assert from 'node:assert/strict'
import test from 'node:test'
import { startExclusiveLoop } from './exclusiveLoop.js'

// A minimal Web Locks model: one holder per name, FIFO waiters, ifAvailable.
function fakeLocks() {
  const held = new Map()
  const waiting = new Map()
  async function grant(name, callback) {
    held.set(name, true)
    try { return await callback({ name }) } finally {
      held.delete(name)
      const next = waiting.get(name)?.shift()
      if (next) void grant(name, next.callback).then(next.resolve, next.reject)
    }
  }
  return {
    request(name, options, callback) {
      if (typeof options === 'function') { callback = options; options = {} }
      if (!held.has(name)) return grant(name, callback)
      if (options.ifAvailable) return Promise.resolve().then(() => callback(null))
      return new Promise((resolve, reject) => {
        if (!waiting.has(name)) waiting.set(name, [])
        waiting.get(name).push({ callback, resolve, reject })
      })
    },
  }
}

function deferred() {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}

test('the owning window resolves only after its first pass finishes, and keeps the lock', async () => {
  const locks = fakeLocks()
  const firstCheck = deferred()
  let settled = false
  const started = startExclusiveLoop(locks, 'loop', async () => { await firstCheck.promise; return true }).then(() => { settled = true })
  await new Promise(r => setTimeout(r, 10))
  assert.equal(settled, false, 'still checking')
  firstCheck.resolve()
  await started
  let otherRan = false
  await startExclusiveLoop(locks, 'loop', async () => { otherRan = true; return true })
  assert.equal(otherRan, false, 'a second window waits instead of running')
})

test('a waiting window resolves at once and takes over when the owner releases', async () => {
  const locks = fakeLocks()
  const ownerDone = deferred()
  await startExclusiveLoop(locks, 'loop', async () => { void ownerDone.promise; return false })
  // Owner released (manual mode): a new owner can start.
  const release = deferred()
  void locks.request('loop', () => release.promise)
  let ran = 0
  await startExclusiveLoop(locks, 'loop', async () => { ran++; return true })
  assert.equal(ran, 0, 'resolved without running while another window holds the lock')
  release.resolve()
  await new Promise(r => setTimeout(r, 10))
  assert.equal(ran, 1, 'took over when the lock was released')
})

test('without Web Locks the first pass still completes before resolving', async () => {
  const pass = deferred()
  let settled = false
  const started = startExclusiveLoop(undefined, 'loop', async () => { await pass.promise; return true }).then(() => { settled = true })
  await new Promise(r => setTimeout(r, 10))
  assert.equal(settled, false)
  pass.resolve()
  await started
})
