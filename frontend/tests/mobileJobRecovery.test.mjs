import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { ref, computed } from 'vue'

function fixture(mobile, initialJobs = []) {
  const source = readFileSync(new URL('../src/composables/useGenerationStatus.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace(/^export /gm, '')
  const handlers = new Map()
  let jobs = initialJobs
  let gate = null
  const make = new Function('ref', 'computed', 'mobileRecoveryEnabled', 'useWebSocket', 'fetch', 'window', `${source}; useGenerationStatus(); return { activeJobsByInstanceId, reconcileJobs, status: useGenerationStatus() }`)
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

const settle = ms => new Promise(resolve => setTimeout(resolve, ms))

test('a tool whose jobs all sit in the queue reads stalled until one starts', () => {
  const f = fixture(false)
  const { isToolStalled } = f.state.status
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-p_t@@a' } })
  assert.equal(isToolStalled('p:t'), true)
  f.emit('generation_job_started', { job: { id: 1, generator_instance_id: 'tool-p_t@@a' } })
  assert.equal(isToolStalled('p:t'), false)
})

test('one tab across two clients is stalled only while neither is moving', () => {
  const f = fixture(false)
  const { isFeedScopeStalled } = f.state.status
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-p_t@@a' } })
  f.emit('generation_job_queued', { job: { id: 2, generator_instance_id: 'tool-p_t@@b' } })
  f.emit('generation_job_started', { job: { id: 2, generator_instance_id: 'tool-p_t@@b' } })
  assert.equal(isFeedScopeStalled('p_t'), false)
  f.emit('generation_job_completed', { job: { id: 2, generator_instance_id: 'tool-p_t@@b' } })
  assert.equal(isFeedScopeStalled('p_t'), true)
})

test('a chat whose generations wait in the queue reads stalled, again after a requeue', () => {
  const f = fixture(false)
  const { isChatGenerationStalled } = f.state.status
  const job = { id: 7, generator_instance_id: 'agent', output_context_kind: 'chat', output_context_id: '42' }
  f.emit('generation_job_queued', { job })
  assert.equal(isChatGenerationStalled(42), true)
  f.emit('generation_job_started', { job })
  assert.equal(isChatGenerationStalled(42), false)
  // A requeue (provider dropped) puts it back to waiting.
  f.emit('generation_job_queued', { job })
  assert.equal(isChatGenerationStalled(42), true)
  f.emit('generation_job_completed', { job })
  assert.equal(isChatGenerationStalled(42), false)
})

test('a page loaded mid-generation learns of jobs already in flight', async () => {
  const f = fixture(false, [{ id: 1, status: 'processing', generator_instance_id: 'tool-p_t' }])
  await settle(10)
  assert.deepEqual(f.state.activeJobsByInstanceId.value, { 'tool-p_t': 1 })
})

test('a job that starts while the snapshot is read is still counted', async () => {
  const f = fixture(false)
  await settle(10)
  const release = f.hold()
  const reconciled = f.state.reconcileJobs()
  // Queued before the page loaded; started between the status reads.
  f.emit('generation_job_started', { job: { id: 5, generator_instance_id: 'tool-p_t' } })
  release()
  await reconciled
  assert.deepEqual(f.state.activeJobsByInstanceId.value, { 'tool-p_t': 1 })
  f.emit('generation_job_completed', { job: { id: 5, generator_instance_id: 'tool-p_t' } })
  assert.deepEqual(f.state.activeJobsByInstanceId.value, {})
})

test('a start announced after its job was cancelled changes nothing', () => {
  const f = fixture(false)
  const { isToolStalled } = f.state.status
  f.emit('generation_job_queued', { job: { id: 1, generator_instance_id: 'tool-p_t' } })
  f.emit('generation_job_queued', { job: { id: 2, generator_instance_id: 'tool-p_t' } })
  f.emit('generation_job_cancelled', { job: { id: 1, generator_instance_id: 'tool-p_t' } })
  f.emit('generation_job_started', { job: { id: 1, status: 'cancelled', generator_instance_id: 'tool-p_t' } })
  assert.deepEqual(f.state.activeJobsByInstanceId.value, { 'tool-p_t': 1 })
  assert.equal(isToolStalled('p:t'), true)
})
