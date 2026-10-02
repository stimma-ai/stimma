import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendProjectId,
  applyMembershipChange,
  assetBrowseScope,
  canRemoveFromProject,
  countMemberships,
  includesProjectAssets,
  membershipState,
  membershipToggleAction,
  orderProjectsCurrentFirst,
  projectListParam,
  resolveProjectId,
  toProjectId,
} from './projectScope.ts'

test('toProjectId accepts positive integers only', () => {
  assert.equal(toProjectId(4), 4)
  assert.equal(toProjectId('12'), 12)
  assert.equal(toProjectId(null), null)
  assert.equal(toProjectId(undefined), null)
  assert.equal(toProjectId(''), null)
  assert.equal(toProjectId(0), null)
  assert.equal(toProjectId(-3), null)
  assert.equal(toProjectId('abc'), null)
})

test('resolveProjectId prefers the explicit owner and respects an explicit null', () => {
  assert.equal(resolveProjectId(7, 3), 7)
  assert.equal(resolveProjectId(undefined, 3), 3)
  assert.equal(resolveProjectId(undefined, undefined, 5), 5)
  // An explicit null (a chat with no project) must not fall through to the active project.
  assert.equal(resolveProjectId(null, 3), null)
  assert.equal(resolveProjectId(), null)
})

test('appendProjectId only adds the field for a project', () => {
  const withProject = appendProjectId(new FormData(), 9)
  assert.equal(withProject.get('project_id'), '9')
  const without = appendProjectId(new FormData(), null)
  assert.equal(without.has('project_id'), false)
})

test('projectListParam sends none for the top level', () => {
  assert.equal(projectListParam(null), 'none')
  assert.equal(projectListParam(4), '4')
})

test('membership counts each target once per project', () => {
  const counts = countMemberships([
    [{ id: 1 }, { id: 2 }],
    [{ id: 1 }, { id: 1 }],
    null,
    [],
  ])
  assert.equal(counts.get(1), 2)
  assert.equal(counts.get(2), 1)
  assert.equal(counts.has(3), false)
})

test('membership state and toggle action', () => {
  const counts = new Map([[1, 3], [2, 1]])
  assert.equal(membershipState(counts, 3, 1), 'all')
  assert.equal(membershipState(counts, 3, 2), 'some')
  assert.equal(membershipState(counts, 3, 9), 'none')
  assert.equal(membershipState(counts, 0, 1), 'none')
  assert.equal(membershipToggleAction('all'), 'remove')
  assert.equal(membershipToggleAction('some'), 'add')
  assert.equal(membershipToggleAction('none'), 'add')
})

test('applyMembershipChange sets every target in or out', () => {
  const counts = new Map([[2, 1]])
  const added = applyMembershipChange(counts, 3, 2, 'add')
  assert.equal(added.get(2), 3)
  assert.equal(counts.get(2), 1, 'input map is not mutated')
  const removed = applyMembershipChange(added, 3, 2, 'remove')
  assert.equal(removed.has(2), false)
})

test('current project is pinned to the top', () => {
  const projects = [{ id: 1, name: 'A' }, { id: 2, name: 'B' }, { id: 3, name: 'C' }]
  assert.deepEqual(orderProjectsCurrentFirst(projects, 3).map(p => p.id), [3, 1, 2])
  assert.deepEqual(orderProjectsCurrentFirst(projects, null).map(p => p.id), [1, 2, 3])
  assert.deepEqual(orderProjectsCurrentFirst(projects, 99).map(p => p.id), [1, 2, 3])
})

test('remove from project needs a scope project that holds a target', () => {
  const counts = new Map([[4, 1]])
  assert.equal(canRemoveFromProject(counts, 4), true)
  assert.equal(canRemoveFromProject(counts, 5), false)
  assert.equal(canRemoveFromProject(counts, null), false)
})

test('top-level browse defaults to unfiled assets', () => {
  assert.equal(assetBrowseScope({}), 'unfiled')
  assert.equal(assetBrowseScope({ includeProjects: true }), 'all')
})

test('project filters imply including project assets', () => {
  assert.equal(includesProjectAssets({ selectedProjects: [3] }), true)
  assert.equal(includesProjectAssets({ projectMembership: 'any' }), true)
  assert.equal(includesProjectAssets({ projectMembership: 'none' }), false)
  assert.equal(assetBrowseScope({ selectedProjects: [3] }), 'all')
  assert.equal(assetBrowseScope({ projectMembership: 'none' }), 'unfiled')
})

test('project and trash views send no scope', () => {
  assert.equal(assetBrowseScope({}, { projectId: 4 }), undefined)
  assert.equal(assetBrowseScope({ includeProjects: true }, { projectId: 4 }), undefined)
  assert.equal(assetBrowseScope({}, { isTrashMode: true }), undefined)
})
