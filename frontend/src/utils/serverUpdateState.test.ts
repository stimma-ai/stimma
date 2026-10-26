import { test } from 'node:test'
import assert from 'node:assert/strict'
import { SERVER_RECONCILE_LIMIT_MS, SERVER_RESTART_GRACE_MS, serverOperationExpired, serverOperationResult,
  serverOperationTracked, type ServerOperation } from './serverUpdateState.ts'

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
test('the client follow-up gets its own window from server confirmation', () => {
  const late = operation.startedAt + SERVER_RESTART_GRACE_MS + 1
  assert.equal(serverOperationExpired(operation, late), true)
  const finished = {...operation, serverFinished: true, serverFinishedAt: late}
  assert.equal(serverOperationExpired(finished, late + SERVER_RESTART_GRACE_MS), false)
  assert.equal(serverOperationExpired(finished, late + SERVER_RESTART_GRACE_MS + 1), true)
})

test('a hidden operation is tracked for a bounded time after its stage began', () => {
  assert.equal(serverOperationTracked(operation, operation.startedAt + SERVER_RESTART_GRACE_MS + 1), true)
  assert.equal(serverOperationTracked(operation, operation.startedAt + SERVER_RECONCILE_LIMIT_MS), false)
})
