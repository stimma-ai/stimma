import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { ref, computed } from 'vue'

function fixture(mobile) {
  const source = readFileSync(new URL('../src/composables/useGenerationStatus.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace(/^export /gm, '')
  const handlers = new Map()
  let jobs = []
  let gate = null
  const make = new Function('ref', 'computed', 'mobileRecoveryEnabled', 'useWebSocket', 'fetch', 'window', `${source}; useGenerationStatus(); return { activeJobsByInstanceId, reconcileJobs }`)
  const state = make(ref, computed, mobile, () => ({ on: (name, fn) => handlers.set(name, fn) }),
    async url => { const snapshot = jobs; await gate; return { ok: true, json: async () => ({ jobs: snapshot.filter(job => job.status === new URL(url, "http://fixture").searchParams.get("status")) }) } }, new EventTarget())
  return { state, emit: (name, data) => handlers.get(name)?.(data), setJobs: value => { jobs = value }, hold: () => { let open; gate = new Promise(resolve => { open = resolve }); return () => { gate = null; open() } } }
}

test('phone counts survive disconnect, then reconcile jobs that finished or started while asleep', async () => {
  const f = fixture(true)
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-fixture' } })
  f.emit('websocket_disconnected')
  assert.equal(f.state.activeJobsByInstanceId.value['tool-fixture'], 1)
  f.setJobs([{ id: 2, status: 'processing', generator_instance_id: 'tool-other' }])
  await f.state.reconcileJobs()
  assert.deepEqual(f.state.activeJobsByInstanceId.value, { 'tool-other': 1 })
  f.setJobs([])
  await f.state.reconcileJobs()
  assert.deepEqual(f.state.activeJobsByInstanceId.value, {})
})

test('desktop disconnect keeps its existing count reset', () => {
  const f = fixture(false)
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-fixture' } })
  f.emit('websocket_disconnected')
  assert.deepEqual(f.state.activeJobsByInstanceId.value, {})
})

test('job events during every snapshot read are merged, never discarded', async () => {
  const f = fixture(true)
  // The snapshot is read before job 2 settles and job 3 is queued; job 1 is still running.
  f.setJobs([{ id: 1, status: 'processing', generator_instance_id: 'tool-a' }, { id: 2, status: 'queued', generator_instance_id: 'tool-a' }])
  const release = f.hold()
  const reconciled = f.state.reconcileJobs()
  f.emit('generation_job_queued', { job: { id: 3, generator_instance_id: 'tool-b' } })
  f.emit('generation_job_completed', { job: { id: 2, generator_instance_id: 'tool-a' } })
  // A requeue broadcast for a job the snapshot already has must not double count.
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-a' } })
  release()
  await reconciled
  assert.deepEqual(f.state.activeJobsByInstanceId.value, { 'tool-a': 1, 'tool-b': 1 })
  // Settling afterwards decrements the merged counts normally.
  f.emit('generation_job_completed', { job: { id: 1, generator_instance_id: 'tool-a' } })
  f.emit('generation_job_failed', { job: { id: 3, generator_instance_id: 'tool-b' } })
  assert.deepEqual(f.state.activeJobsByInstanceId.value, {})
})

test('desktop rebuilds its counts from the server once the socket is back', async () => {
  const f = fixture(false)
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-fixture' } })
  f.emit('websocket_disconnected')
  assert.deepEqual(f.state.activeJobsByInstanceId.value, {})
  // Still running on the server (a remote device, or a restarted backend that requeued it).
  f.setJobs([{ id: 1, status: 'processing', generator_instance_id: 'tool-fixture' }])
  f.emit('websocket_reconnected', { generation: 2 })
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.deepEqual(f.state.activeJobsByInstanceId.value, { 'tool-fixture': 1 })
})
