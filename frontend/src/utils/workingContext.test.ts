import assert from 'node:assert/strict'
import test from 'node:test'
import { assetLinkContext, belongsToContext, contextRoute, contextSection, contextSwitchRoute, projectIdFrom } from './workingContext.ts'

test('all browser sections follow context and retain their section when switching', () => {
  for (const section of ['home', 'browse', 'boards', 'chats', 'flows', 'all-tools']) {
    const scoped = contextRoute(section, 17)
    assert.equal(contextSection(scoped.name), section)
    assert.deepEqual(contextSwitchRoute({ name: scoped.name, params: { id: '17' } }, 22), contextRoute(section, 22))
    assert.deepEqual(contextSwitchRoute({ name: scoped.name, params: { id: '17' } }, null), { name: section })
  }
})

test('switching with a tool open reuses the destination instance or lands on its overview', () => {
  const tool = { name: 'tool', params: { fullToolId: 'test:edit' }, query: { instance: '7', remixFrom: '52' } } as any
  const instances: Record<string, string> = { 'test:edit@22': '9' }
  const find = (id: string, project: number | null) => instances[`${id}@${project}`] ?? null
  assert.deepEqual(contextSwitchRoute(tool, 22, find), {
    name: 'tool', params: { fullToolId: 'test:edit' }, query: { project_id: '22', instance: '9' },
  })
  // No instance in the destination: never mint one, go to the overview.
  assert.deepEqual(contextSwitchRoute(tool, 23, find), { name: 'project-overview', params: { id: '23' } })
  assert.deepEqual(contextSwitchRoute(tool, null, find), { name: 'home' })
  assert.deepEqual(contextSwitchRoute(tool, 22), { name: 'project-overview', params: { id: '22' } })
  assert.deepEqual(contextSwitchRoute({ name: 'chat', params: { id: '52' } }, 22), { name: 'project-chats', params: { id: '22' } })
})

test('asset deep links keep a containing or Everything context, else pick the most recent project', () => {
  assert.equal(assetLinkContext(null, [3, 4]), null)
  assert.equal(assetLinkContext(4, [3, 4]), 4)
  assert.equal(assetLinkContext(5, []), null)
  assert.equal(assetLinkContext(5, [3, 4], [9, 4, 3]), 4)
  assert.equal(assetLinkContext(5, [3, 4], [9]), 3)
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
