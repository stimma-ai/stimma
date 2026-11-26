import assert from 'node:assert/strict'
import test from 'node:test'

import { elementInstructionsMarkdown, familyLabel, isVideoFormat } from './elementText.ts'

test('drops the leading name heading and reflows wrapped lines', () => {
  const md = '# Old Wen\n\nAn elderly vendor,\nalways with a towel.\n\n## Always the same\n- Face and\n  build.\n- Gray hair.\n'
  assert.equal(
    elementInstructionsMarkdown(md),
    'An elderly vendor, always with a towel.\n\n## Always the same\n- Face and build.\n- Gray hair.\n',
  )
})

test('keeps fenced code as written', () => {
  const md = 'Use:\n\n```\nline one\nline two\n```\n'
  assert.equal(elementInstructionsMarkdown(md), md)
})

test('labels model families and recognizes video', () => {
  assert.equal(familyLabel('flux-3-klein'), 'Flux 3 Klein')
  assert.equal(familyLabel(''), '')
  assert.equal(isVideoFormat('MP4'), true)
  assert.equal(isVideoFormat('png'), false)
})
