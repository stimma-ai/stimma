import assert from 'node:assert/strict'
import test from 'node:test'
import { busyContexts, busyElsewhere, parseActivity, projectIdFromInstanceId } from './projectActivity.ts'

test('server activity payloads parse from REST and websocket shapes', () => {
  const entries = [{ project_id: null, running_jobs: 1 }, { project_id: 4, running_chats: 2 }]
  assert.deepEqual(parseActivity({ activity: entries }), entries)
  assert.deepEqual(parseActivity(entries), entries)
  assert.deepEqual(parseActivity({ activity: [{ project_id: 'x' }, null] }), [])
  assert.deepEqual(parseActivity(undefined), [])
})

test('tool instances map to their project, unscoped instances to the top level', () => {
  assert.equal(projectIdFromInstanceId('tool-builtin_x__project_12@@abc'), 12)
  assert.equal(projectIdFromInstanceId('tool-builtin_x__project_12__i_3'), 12)
  assert.equal(projectIdFromInstanceId('tool-builtin_x@@abc'), null)
})

test('server and local activity merge; zero counts and settled instances are ignored', () => {
  const busy = busyContexts(
    [{ project_id: 3, running_flows: 1 }, { project_id: 9, running_jobs: 0 }],
    { 'tool-a__project_5@@1': 2, 'tool-b@@2': 0 },
    { 'tool-c@@3': true },
    { 'chat-7': 1 },
  )
  assert.deepEqual([...busy].sort(), [3, 5, null].sort())
})

test('activity elsewhere excludes only the current context', () => {
  const busy = new Set<number | null>([4])
  assert.equal(busyElsewhere(busy, 4), false)
  assert.equal(busyElsewhere(busy, null), true)
  assert.equal(busyElsewhere(new Set([null]), 4), true)
  assert.equal(busyElsewhere(new Set(), 4), false)
})
