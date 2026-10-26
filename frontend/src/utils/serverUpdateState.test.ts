import { test } from 'node:test'
import assert from 'node:assert/strict'
import { MACHINE_FOLLOW_UP_MS, SERVER_RESTART_GRACE_MS, serverOperationExpired, serverOperationResult, type ServerOperation } from './serverUpdateState.ts'

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
  const checked = {...operation, serverFinished:true, machineCheckedAt: late}
  assert.equal(serverOperationExpired(checked, late + MACHINE_FOLLOW_UP_MS), false)
  assert.equal(serverOperationExpired(checked, late + MACHINE_FOLLOW_UP_MS + 1), true)
})
