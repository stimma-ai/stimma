import assert from 'node:assert/strict'
import test from 'node:test'
import { belongsToContext, contextRoute, contextSection, contextSwitchRoute, projectIdFrom } from './workingContext.ts'

test('all browser sections follow context and retain their section when switching', () => {
  for (const section of ['home', 'browse', 'boards', 'chats', 'flows', 'all-tools']) {
    const scoped = contextRoute(section, 17)
    assert.equal(contextSection(scoped.name), section)
    assert.deepEqual(contextSwitchRoute({ name: scoped.name, params: { id: '17' } }, 22), contextRoute(section, 22))
    assert.deepEqual(contextSwitchRoute({ name: scoped.name, params: { id: '17' } }, null), { name: section })
  }
})

test('switching a tool opens a session in the destination rather than reusing the source session or its inputs', () => {
  assert.deepEqual(contextSwitchRoute({ name: 'tool', params: { fullToolId: 'test:edit' }, query: { instance: '7', remixFrom: '52' } } as any, 22), {
    name: 'tool', params: { fullToolId: 'test:edit' }, query: { project_id: '22' },
  })
  assert.deepEqual(contextSwitchRoute({ name: 'chat', params: { id: '52' } }, 22), { name: 'project-chats', params: { id: '22' } })
})

test('shared Assets keep one editor document while sessions are strictly owned', () => {
  assert.equal(belongsToContext({ type: 'tool', projectId: 17 }, 22), false)
  assert.equal(belongsToContext({ type: 'tool', projectId: 17 }, null), false)
  assert.equal(belongsToContext({ type: 'tool' }, null), true)
  const editor = { type: 'editor', contextProjectIds: [17, null] }
  assert.equal(belongsToContext(editor, 17), true)
  assert.equal(belongsToContext(editor, null), true)
  assert.equal(belongsToContext(editor, 22), false)
  assert.equal(belongsToContext({ type: 'project', projectId: 17 }, 17), false)
})

test('invalid persisted context IDs cannot become output destinations', () => {
  for (const value of [null, undefined, '', '0', '-1', '12oops', '1.2', Number.MAX_SAFE_INTEGER + 1]) assert.equal(projectIdFrom(value), null)
  assert.equal(projectIdFrom(['17', '22']), 17)
})
