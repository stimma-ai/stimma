import assert from 'node:assert/strict'
import test from 'node:test'
import { createMaintenanceQueue } from './startupMaintenance.js'

const tick = () => new Promise(resolve => setImmediate(resolve))

function fakeTimers() {
  let now = 0
  let next = 1
  const pending = new Map()
  return {
    setTimeout(fn, ms) { const id = next++; pending.set(id, { fn, at: now + ms }); return id },
    clearTimeout(id) { pending.delete(id) },
    async advance(ms) {
      const end = now + ms
      for (;;) {
        await tick()
        const due = [...pending].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
        if (!due) break
        pending.delete(due[0])
        now = due[1].at
        due[1].fn()
      }
      now = end
      await tick()
    },
  }
}

function recorder() {
  const log = []
  const task = (name, finish) => () => {
    log.push(`start ${name}`)
    return finish.then(() => log.push(`end ${name}`))
  }
  return { log, task }
}

test('nothing runs before the UI is usable; then tasks run one at a time', async () => {
  const timers = fakeTimers()
  const queue = createMaintenanceQueue({ settleMs: 100, gapMs: 10, timers })
  const { log, task } = recorder()
  let finishA
  const a = new Promise(resolve => { finishA = resolve })
  queue.schedule('a', task('a', a))
  queue.schedule('b', task('b', Promise.resolve()))
  await timers.advance(1000)
  assert.deepEqual(log, [], 'startup is not usable yet')
  queue.markUsable()
  await timers.advance(99)
  assert.deepEqual(log, [], 'waits for the settle delay')
  await timers.advance(1)
  assert.deepEqual(log, ['start a'])
  await timers.advance(500)
  assert.deepEqual(log, ['start a'], 'b waits for a')
  finishA()
  await timers.advance(10)
  assert.deepEqual(log, ['start a', 'end a', 'start b', 'end b'])
})

test('a slow task stops holding the queue after its budget but keeps running', async () => {
  const timers = fakeTimers()
  const queue = createMaintenanceQueue({ settleMs: 0, gapMs: 0, taskBudgetMs: 50, timers })
  const { log, task } = recorder()
  queue.schedule('slow', task('slow', new Promise(() => {})))
  queue.schedule('next', task('next', Promise.resolve()))
  queue.markUsable()
  await timers.advance(49)
  assert.deepEqual(log, ['start slow'])
  await timers.advance(1)
  assert.deepEqual(log, ['start slow', 'start next', 'end next'])
})

test('maintenance still runs if startup never reports usable', async () => {
  const timers = fakeTimers()
  const queue = createMaintenanceQueue({ settleMs: 0, startAnywayMs: 1000, timers })
  const { log, task } = recorder()
  queue.schedule('a', task('a', Promise.resolve()))
  await timers.advance(999)
  assert.deepEqual(log, [])
  await timers.advance(1)
  assert.deepEqual(log, ['start a', 'end a'])
})

test('a task queued twice runs once; later tasks run promptly without a second settle', async () => {
  const timers = fakeTimers()
  const queue = createMaintenanceQueue({ settleMs: 100, gapMs: 0, timers })
  const { log, task } = recorder()
  const first = queue.schedule('sync', task('sync', Promise.resolve()))
  const second = queue.schedule('sync', task('sync again', Promise.resolve()))
  assert.equal(first, second)
  queue.markUsable()
  await timers.advance(100)
  assert.deepEqual(log, ['start sync', 'end sync'])
  queue.schedule('account', task('account', Promise.resolve()))
  await timers.advance(0)
  assert.deepEqual(log, ['start sync', 'end sync', 'start account', 'end account'])
})

test('a failing task does not stop the queue or surface as unhandled', async () => {
  const timers = fakeTimers()
  const queue = createMaintenanceQueue({ settleMs: 0, gapMs: 0, timers })
  const { log, task } = recorder()
  const failed = queue.schedule('bad', () => { throw new Error('offline') })
  queue.schedule('good', task('good', Promise.resolve()))
  queue.markUsable()
  await timers.advance(0)
  await assert.rejects(failed, /offline/)
  assert.deepEqual(log, ['start good', 'end good'])
})
