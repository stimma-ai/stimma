import assert from 'node:assert/strict'
import test from 'node:test'
import { countOutside, outsideLabel, recentsInScope } from './searchScope.ts'

test('matches outside a project count other projects\' items, other projects and extra assets', () => {
  const global = {
    chats: [{ id: 1, project_id: 7 }, { id: 2, project_id: 8 }, { id: 3, project_id: null }],
    flows: [{ id: 4, project_id: 7 }],
    boards: [],
    projects: [{ id: 7 }, { id: 9 }],
  }
  assert.deepEqual(countOutside(global, 7, 20, { scoped: 4, global: 10 }), { count: 2 + 0 + 1 + 6, capped: false })
})

test('nothing outside yields zero, and a full category marks the count as capped', () => {
  assert.deepEqual(countOutside({ chats: [{ id: 1, project_id: 7 }] }, 7, 20), { count: 0, capped: false })
  assert.deepEqual(countOutside(null, 7, 20, { scoped: 5, global: 3 }), { count: 0, capped: false })
  const full = { chats: [{ id: 1, project_id: 8 }, { id: 2, project_id: 8 }] }
  assert.deepEqual(countOutside(full, 7, 2), { count: 2, capped: true })
})

test('the outside row reads naturally', () => {
  assert.equal(outsideLabel({ count: 1, capped: false }, 'Spring'), '1 more result outside Spring')
  assert.equal(outsideLabel({ count: 12, capped: true }, ''), '12+ more results outside Untitled project')
})

test('scoped recents keep the project\'s items and tools only', () => {
  const entries = [
    { type: 'chat', id: '1', projectId: 7 },
    { type: 'chat', id: '2', projectId: null },
    { type: 'board', id: '3' },
    { type: 'tool', id: 'x' },
    { type: 'project', id: '7', projectId: 7 },
  ]
  assert.deepEqual(recentsInScope(entries, 7).map(e => e.id), ['1', 'x'])
  assert.equal(recentsInScope(entries, null).length, 5)
})
