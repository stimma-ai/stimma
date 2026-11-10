import test from 'node:test'
import assert from 'node:assert/strict'
import { programLabel, programSections, subjectOfId } from './programChoiceLayout.ts'
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
  assert.equal(programLabel('Colors'), 'Colors')
  const people = [{ id: 'people', label: 'People', count: 3, source: 'text' }]
  assert.deepEqual(programSections([pick('x', { group: 'people', index: 3 }), pick('y', { group: 'people', index: 1 })], people).map(s => s.label), ['Person 1', 'Person 3'])
})

const shape = (sections: ReturnType<typeof programSections>) => sections.map(s => [s.kind, s.label, s.choices.map(c => c.id)])

test('the payload decides: scene first, then shared, then each subject in declared order', () => {
  const sections = programSections([
    pick('woman.hairstyle', { group: 'woman', attr: 'hairstyle' }),
    pick('place'),
    pick('friends[2].age', { group: 'friends', index: 2 }),
    pick('outfit', { shared: true }),
    pick('outfit.colors', { follows: 'outfit' }),
    pick('friends[1].age', { group: 'friends', index: 1 }),
    pick('woman.outfit', { group: 'woman' }),
    pick('woman.outfit.colors', { group: 'woman' }),
  ], [{ id: 'friends', label: 'Friends', count: 2, source: 'text' }, { id: 'woman', label: 'Woman', count: 1, source: 'added' }])
  assert.deepEqual(shape(sections), [
    ['scene', '', ['place']],
    ['shared', 'Shared', ['outfit', 'outfit.colors']],
    ['subject', 'Friend 1', ['friends[1].age']],
    ['subject', 'Friend 2', ['friends[2].age']],
    ['subject', 'Woman', ['woman.hairstyle', 'woman.outfit', 'woman.outfit.colors']],
  ])
})

test('one subject has no header, grouped or not', () => {
  assert.deepEqual(shape(programSections([pick('woman.hair', { group: 'woman' }), pick('place')], [])), [['scene', '', ['woman.hair', 'place']]])
  assert.deepEqual(shape(programSections([pick('woman.hair'), pick('woman.outfit'), pick('place')], [])), [['scene', '', ['woman.hair', 'woman.outfit', 'place']]])
})

test('a partly grouped program shows its plain details with the scene, never under a subject', () => {
  const sections = programSections([
    pick('woman1.age', { group: 'woman', index: 1 }), pick('hairstyle'), pick('woman2.age', { group: 'woman', index: 2 }),
  ], [{ id: 'woman', label: 'Woman', count: 2, source: 'added' }])
  assert.deepEqual(shape(sections), [['scene', '', ['hairstyle']], ['subject', 'Woman 1', ['woman1.age']], ['subject', 'Woman 2', ['woman2.age']]])
})

test('programs prepared before choices carried subjects are grouped by their ids', () => {
  const sections = programSections([
    pick('woman1.age'), pick('woman1.outfit'), pick('woman1.outfit.colors'), pick('woman2.age'), pick('cafe'), pick('outfit.colors'),
  ], [])
  assert.deepEqual(shape(sections), [['scene', '', ['cafe', 'outfit.colors']], ['subject', 'Woman 1', ['woman1.age', 'woman1.outfit', 'woman1.outfit.colors']], ['subject', 'Woman 2', ['woman2.age']]])
  assert.deepEqual(subjectOfId('mother.outfit'), { group: 'mother' })
  assert.deepEqual(subjectOfId('friends[2].outfit.colors'), { group: 'friends', index: 2 })
  assert.deepEqual(subjectOfId('woman_2.hair'), { group: 'woman', index: 2 })
  assert.equal(subjectOfId('outfit.colors'), null)
  assert.equal(subjectOfId('outfit.colours'), null)  // an id recorded before the US spelling
  assert.equal(subjectOfId('param.steps'), null)
  assert.equal(subjectOfId('weather'), null)
})

test("choices that hold the user's own words follow the ones that vary", () => {
  const sections = programSections([pick('car', { said: 'yellow ferrari' }), pick('sky'), pick('light')], [])
  assert.deepEqual(sections[0].choices.map(c => c.id), ['sky', 'light', 'car'])
})

test("a choice holding the user's words sits in its subject's section, after that subject's varying ones", () => {
  const sections = programSections([
    pick('mother.outfit', { group: 'mother', attr: 'outfit', said: 'red dress' }),
    pick('mother.hair', { group: 'mother', attr: 'hair' }),
    pick('daughter.hair', { group: 'daughter', attr: 'hair' }),
    pick('place'),
  ], [])
  assert.deepEqual(shape(sections), [
    ['scene', '', ['place']],
    ['subject', 'Mother', ['mother.hair', 'mother.outfit']],
    ['subject', 'Daughter', ['daughter.hair']],
  ])
  // programs prepared before choices carried their subject: the id still decides
  const legacy = programSections([pick('mother.outfit', { said: 'red dress' }), pick('mother.hair'), pick('daughter.hair')], [])
  assert.deepEqual(shape(legacy).map(s => s[2]), [['mother.hair', 'mother.outfit'], ['daughter.hair']])
})
