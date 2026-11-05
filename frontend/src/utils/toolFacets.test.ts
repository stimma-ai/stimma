import assert from 'node:assert/strict'
import test from 'node:test'

import { MEDIA_FILTER_OPTIONS, takesFact, toolMakesAudio, toolMatchesMediaFilters, toolTakes } from './toolFacets.ts'

// Catalog summaries carry only a parameter outline; full tools carry parameter_schema.
const outline = (properties: Record<string, any>) => ({ parameter_outline: { properties } })

const textToImage = { task_types: ['text-to-image'], ...outline({}) }
const imageToVideo = { task_types: ['image-to-video'], ...outline({ input_images: { type: 'array' } }) }
const avatar = {
  task_types: ['image-to-video'],
  ...outline({ input_images: { type: 'array' }, input_audios: { type: 'array' } }),
}
const filter = {
  task_types: ['filter'],
  ...outline({ input_images: { type: 'array', 'x-accept-media': ['image', 'video'] } }),
}
const speech = { task_types: ['text-to-speech'], ...outline({}) }
const voiceChanger = { task_types: ['audio-to-audio'], ...outline({ input_audios: { type: 'array' } }) }
const unknown = { task_types: ['text-to-image'] }

test('takes reads the media slots in image, video, audio order', () => {
  assert.deepEqual(toolTakes(textToImage), [])
  assert.deepEqual(toolTakes(imageToVideo), ['image'])
  assert.deepEqual(toolTakes(avatar), ['image', 'audio'])
  assert.deepEqual(toolTakes(filter), ['image', 'video'])
})

test('a tool with no schema or outline has unknown input and never matches a takes filter', () => {
  assert.equal(toolTakes(unknown), null)
  assert.equal(toolMatchesMediaFilters(unknown, new Set(['takes:image'])), false)
  assert.equal(takesFact(unknown), '')
})

test('makes audio follows the audio-output task types', () => {
  assert.equal(toolMakesAudio(speech), true)
  assert.equal(toolMakesAudio(voiceChanger), true)
  assert.equal(toolMakesAudio({ task_types: [], task_type: 'text-to-music' }), true)
  assert.equal(toolMakesAudio(imageToVideo), false)
})

test('selected options all have to match, and none selected passes every tool', () => {
  assert.equal(toolMatchesMediaFilters(textToImage, new Set()), true)
  assert.equal(toolMatchesMediaFilters(avatar, new Set(['takes:image', 'takes:audio'])), true)
  assert.equal(toolMatchesMediaFilters(imageToVideo, new Set(['takes:image', 'takes:audio'])), false)
  assert.equal(toolMatchesMediaFilters(voiceChanger, new Set(['takes:audio', 'makes:audio'])), true)
  assert.equal(toolMatchesMediaFilters(speech, new Set(['takes:audio', 'makes:audio'])), false)
})

test('the card fact lists what the tool takes and is empty for text-only tools', () => {
  assert.equal(takesFact(textToImage), '')
  assert.equal(takesFact(avatar), 'takes image, audio')
})

test('every filter option id is one the matcher knows', () => {
  for (const option of MEDIA_FILTER_OPTIONS) {
    assert.equal(option.id.startsWith(`${option.group}:`), true)
    assert.doesNotThrow(() => toolMatchesMediaFilters(avatar, new Set([option.id])))
  }
})
