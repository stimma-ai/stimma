import test from 'node:test'
import assert from 'node:assert/strict'
import { programLabel, programSections } from './programChoiceLayout.ts'
import type { ProgramChoice } from '../composables/usePromptProgram'

const pick = (id: string, extra: Partial<ProgramChoice> = {}): ProgramChoice => ({ id, label: id, kind: 'pick', source: 'text', options: [], ...extra })

test('shared controls lead, numbered subjects sort, and dependent chains stay with their subject', () => {
  const sections = programSections([
    pick('outfit2', { group: 'friends', index: 2 }),
    pick('palette2', { follows: 'outfit2' }),
    pick('setting'),
    pick('outfit1', { group: 'friends', index: 1 }),
    pick('palette1', { follows: 'outfit1' }),
    pick('detail1', { parent: 'palette1' }),
  ], [{ id: 'friends', label: 'Friends', count: 2, source: 'text' }])
  assert.deepEqual(sections.map(s => [s.label, s.choices.map(c => c.id)]), [
    ['', ['setting']], ['Friend 1', ['outfit1', 'palette1', 'detail1']], ['Friend 2', ['outfit2', 'palette2']],
  ])
})

test('cycles and missing dependencies stay shared; no empty subjects are invented', () => {
  const sections = programSections([pick('a', { follows: 'b' }), pick('b', { follows: 'a' }), pick('c', { follows: 'missing' })], [])
  assert.equal(sections.length, 1)
  assert.equal(sections[0].choices.length, 3)
  assert.deepEqual(programSections([], []), [])
})

test('UI labels use US color spelling without changing ids or option text', () => {
  assert.equal(programLabel('Hair colour'), 'Hair color')
  assert.equal(programLabel('Colours'), 'Colors')
  assert.equal(programSections([pick('x', { group: 'people', index: 3 })], [{ id: 'people', label: 'People', count: 3, source: 'text' }])[0].label, 'Person 3')
})

test("choices that hold the user's own words follow the ones that vary", () => {
  const sections = programSections([pick('car', { said: 'yellow ferrari' }), pick('sky'), pick('light')], [])
  assert.deepEqual(sections[0].choices.map(c => c.id), ['sky', 'light', 'car'])
})
