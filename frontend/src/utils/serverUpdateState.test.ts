import { test } from 'node:test'
import assert from 'node:assert/strict'
import { MACHINE_CHECK_ATTEMPTS, MACHINE_CHECK_RETRY_MS, SERVER_RESTART_GRACE_MS, machineFollowUpStep, serverOperationExpired, serverOperationResult, type ServerOperation } from './serverUpdateState.ts'

const operation: ServerOperation = { deviceId: 'server', name: 'Server', action: 'update', startedAt: 100,
  fromVersion: '1.0.0', targetVersion: '1.1.0', fromStartedAt: 10, sawTransition: false,
  updateMachine: true, machineTarget: '1.1.0' }

test('accepting a queued request does not complete an update', () => {
  assert.equal(serverOperationResult(operation, {status:'ready',version:'1.0.0'}), 'pending')
})
test('a new version must be ready before the client can update', () => {
  assert.equal(serverOperationResult(operation, {status:'starting',version:'1.1.0'}), 'pending')
  assert.equal(serverOperationResult(operation, {status:'ready',version:'1.1.0'}), 'complete')
  assert.equal(serverOperationResult(operation, {status:'ready',version:'1.1.1'}), 'complete')
})
test('returning on the old version restores ordinary update availability', () => {
  assert.equal(serverOperationResult({...operation,sawTransition:true}, {status:'ready',version:'1.0.0'}), 'unchanged')
})
test('restart completion uses the server process identity without requiring a missed poll', () => {
  const restart = {...operation, action:'restart' as const}
  assert.equal(serverOperationResult(restart, {status:'ready',serverStartedAt:10}), 'pending')
  assert.equal(serverOperationResult(restart, {status:'ready',serverStartedAt:11}), 'complete')
  assert.equal(serverOperationResult({...restart,sawTransition:true}, {status:'ready'}), 'complete')
})
test('the client follow-up is not on the server restart clock', () => {
  const late = operation.startedAt + SERVER_RESTART_GRACE_MS + 1
  assert.equal(serverOperationExpired(operation, late), true)
  assert.equal(serverOperationExpired({...operation,serverFinished:true}, late * 10), false)
})

const finished: ServerOperation = {...operation, serverFinished: true}
const idleClient = { currentVersion: '1.0.0', available: false, busy: false, lastCheckedAt: 'a' }

test('the client follow-up checks, then installs what the check found', () => {
  assert.equal(machineFollowUpStep(finished, idleClient, 0), 'check')
  const requested = {...finished, machineCheckRequestedAt: 0, machineCheckBaseline: 'a', machineCheckAttempts: 1}
  assert.equal(machineFollowUpStep(requested, {...idleClient, available: true}, 1), 'install')
  assert.equal(machineFollowUpStep(requested, {...idleClient, currentVersion: '1.1.0'}, 1), 'done')
})

test('a slow or forwarded check keeps the follow-up alive until it reports', () => {
  const requested = {...finished, machineCheckRequestedAt: 0, machineCheckBaseline: 'a', machineCheckAttempts: 1}
  // Requested but not reported yet (forwarded to another window).
  assert.equal(machineFollowUpStep(requested, idleClient, 1), 'wait')
  // Checking or downloading for a long time is still progress.
  assert.equal(machineFollowUpStep(requested, {...idleClient, busy: true}, 60 * 60_000), 'wait')
  // A completed check that found nothing ends it.
  assert.equal(machineFollowUpStep(requested, {...idleClient, lastCheckedAt: 'b'}, 2), 'done')
})

test('a check that never completes is retried a bounded number of times', () => {
  const requested = {...finished, machineCheckRequestedAt: 0, machineCheckBaseline: 'a', machineCheckAttempts: 1}
  assert.equal(machineFollowUpStep(requested, idleClient, MACHINE_CHECK_RETRY_MS), 'check')
  assert.equal(machineFollowUpStep({...requested, machineCheckAttempts: MACHINE_CHECK_ATTEMPTS}, idleClient, MACHINE_CHECK_RETRY_MS), 'give-up')
})
