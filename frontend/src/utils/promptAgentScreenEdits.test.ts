import assert from 'node:assert/strict'
import test from 'node:test'
import { afterAgentTool, coEditedText, isPromptCleared, screenEditsSince } from './promptAgentScreenEdits.ts'

test('reads the prompt and Instructions from a state context', () => {
  assert.deepEqual(
    coEditedText({ prompt: 'a cat', notes: { instructions: 'soft light' }, batch_size: 1 }),
    { prompt: 'a cat', instructions: 'soft light' },
  )
})

test('a screen without a prompt editor reports no prompt', () => {
  assert.deepEqual(coEditedText({ notes: { instructions: '' } }), { instructions: '' })
})

test('reports each changed field with before and after', () => {
  assert.deepEqual(
    screenEditsSince(
      { prompt: 'a dog', instructions: 'keep it warm' },
      { prompt: 'a cat', instructions: 'keep it cold' },
    ),
    [
      { field: 'prompt', before: 'a dog', after: 'a cat' },
      { field: 'instructions', before: 'keep it warm', after: 'keep it cold' },
    ],
  )
})

test('clearing the prompt is an edit', () => {
  assert.deepEqual(screenEditsSince({ prompt: 'a dog' }, { prompt: '' }), [
    { field: 'prompt', before: 'a dog', after: '' },
  ])
})

test('unchanged text and stray whitespace are not edits', () => {
  assert.deepEqual(screenEditsSince({ prompt: 'a dog' }, { prompt: 'a dog' }), [])
  assert.deepEqual(screenEditsSince({ prompt: 'a dog' }, { prompt: 'a dog\n' }), [])
})

test('a field missing on either side is not an edit', () => {
  assert.deepEqual(screenEditsSince({ prompt: 'a dog' }, {}), [])
  assert.deepEqual(screenEditsSince({}, { prompt: 'a dog' }), [])
})

test('only an emptied prompt counts as cleared', () => {
  assert.equal(isPromptCleared({ field: 'prompt', before: 'a dog', after: '  ' }), true)
  assert.equal(isPromptCleared({ field: 'prompt', before: 'a dog', after: 'a cat' }), false)
  assert.equal(isPromptCleared({ field: 'instructions', before: 'warm', after: '' }), false)
})

test('an agent edit is not reported as the user\'s', () => {
  const seen = afterAgentTool({ prompt: 'a dog' }, { prompt: 'a dog' }, { prompt: 'a red dog' })
  assert.deepEqual(screenEditsSince(seen, { prompt: 'a red dog' }), [])
})

test('a hand edit during a request survives a tool that left that field alone', () => {
  // The user cleared the prompt while a parameter change was pending.
  const seen = afterAgentTool({ prompt: 'a dog' }, { prompt: '' }, { prompt: '' })
  assert.deepEqual(screenEditsSince(seen, { prompt: '' }), [{ field: 'prompt', before: 'a dog', after: '' }])
})
