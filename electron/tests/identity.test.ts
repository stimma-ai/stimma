import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'

import { resolveIdentity } from '../src/identity.ts'

const saved = process.env.STIMMA_DISTRIBUTION

afterEach(() => {
  if (saved === undefined) delete process.env.STIMMA_DISTRIBUTION
  else process.env.STIMMA_DISTRIBUTION = saved
})

test('packaged official builds resolve as official without any env', () => {
  delete process.env.STIMMA_DISTRIBUTION
  assert.equal(resolveIdentity('ai.stimma.stimma', 'official').distribution, 'official')
})

test('unstamped builds resolve as dev', () => {
  delete process.env.STIMMA_DISTRIBUTION
  assert.equal(resolveIdentity('ai.stimma.stimma').distribution, 'dev')
  assert.equal(resolveIdentity('ai.stimma.stimma', 'anything-else').distribution, 'dev')
})

test('STIMMA_DISTRIBUTION env overrides the packaged value', () => {
  process.env.STIMMA_DISTRIBUTION = 'official'
  assert.equal(resolveIdentity('ai.stimma.stimma.debug').distribution, 'official')
  process.env.STIMMA_DISTRIBUTION = 'dev'
  assert.equal(resolveIdentity('ai.stimma.stimma', 'official').distribution, 'dev')
})
