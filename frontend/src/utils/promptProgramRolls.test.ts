import test from 'node:test'
import assert from 'node:assert/strict'
import { promptProgramRolls } from './promptProgramRolls.ts'

const roll = (text: string, values: Record<string, string>, extra: any = {}) => {
  const spans: Array<[number, number, string]> = []
  for (const [id, v] of Object.entries(values)) {
    const i = text.indexOf(v)
    spans.push([i, i + v.length, id])
  }
  spans.sort((a, b) => a[0] - b[0])
  return { text, spans, values, scores: {}, ...extra }
}

test('one roll: the prompt with its choices', () => {
  const run = { view: roll('A nun under dawn light', { job: 'nun', light: 'dawn light' }) }
  const [only, ...rest] = promptProgramRolls(run)
  assert.equal(rest.length, 0)
  assert.equal(only.used, true)
  assert.deepEqual(only.pieces, [
    { text: 'A ' }, { text: 'nun', id: 'job' }, { text: ' under ' }, { text: 'dawn light', id: 'light' },
  ])
})

test('each reroll marks what changed, with the rejected value and its score', () => {
  const run = {
    fix: {
      chosen: 2,
      rounds: [
        roll('A nun under moonlight', { job: 'nun', light: 'moonlight' },
          { scores: { job: 0.01, light: 0.93 }, rerolled: { id: 'light', value: 'moonlight' } }),
        roll('A surgeon under noon sun', { job: 'surgeon', light: 'noon sun' },
          { scores: { job: 0.7, light: 0.02 }, rerolled: { id: 'job', value: 'surgeon' } }),
        roll('A nurse under noon sun', { job: 'nurse', light: 'noon sun' }),
      ],
    },
  }
  const rolls = promptProgramRolls(run)
  assert.deepEqual(rolls.map(r => r.used), [false, false, true])
  assert.ok(rolls[0].pieces.every(p => p.was == null))
  const light = rolls[1].pieces.find(p => p.id === 'light')!
  assert.deepEqual(light, { text: 'noon sun', id: 'light', was: 'moonlight', score: 0.93 })
  // a value that changed without being the one rerolled (it followed another) is struck too, with no score
  const job = rolls[1].pieces.find(p => p.id === 'job')!
  assert.deepEqual(job, { text: 'surgeon', id: 'job', was: 'nun' })
  assert.equal(rolls[2].pieces.find(p => p.id === 'light')!.was, undefined)
  assert.equal(rolls[2].pieces.find(p => p.id === 'job')!.was, 'surgeon')
})

test('the best roll is the one used, even when a later one exists', () => {
  const run = { fix: { chosen: 0, rounds: [roll('A b', { x: 'b' }, { rerolled: { id: 'x', value: 'b' } }), roll('A c', { x: 'c' })] } }
  assert.deepEqual(promptProgramRolls(run).map(r => r.used), [true, false])
})

test('records from before rolls show the prompt alone', () => {
  assert.deepEqual(promptProgramRolls({ prompt: 'A nun', fix: { rounds: [{ scores: {} }] } }),
    [{ pieces: [{ text: 'A nun' }], used: true }])
  assert.deepEqual(promptProgramRolls(null), [])
})
