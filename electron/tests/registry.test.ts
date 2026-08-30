import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { WindowRegistry, profileWindowLabel } from '../src/registry.ts'

test('registry round-trips through disk', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-registry-test-'))

  const registry = new WindowRegistry(dir)
  assert.deepEqual(registry.snapshot(), [])

  registry.setProfile('main', 'profile-a')
  registry.setProfile('profile-b', 'b')

  const reloaded = new WindowRegistry(dir)
  assert.equal(reloaded.profileFor('main'), 'profile-a')
  assert.equal(reloaded.labelForProfile('b'), 'profile-b')

  reloaded.remove('main')
  const again = new WindowRegistry(dir)
  assert.equal(again.snapshot().length, 1)
  assert.equal(again.profileFor('main'), null)

  fs.rmSync(dir, { recursive: true, force: true })
})

test('registry reads the Tauri-era windows.json format', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-registry-test-'))
  // Exact shape persisted by src-tauri/src/windows.rs (serde_json pretty).
  fs.writeFileSync(
    path.join(dir, 'windows.json'),
    JSON.stringify(
      {
        windows: [
          { label: 'main', profile_id: 'abc-123' },
          { label: 'profile-def', profile_id: 'def' },
        ],
      },
      null,
      2,
    ),
  )
  const registry = new WindowRegistry(dir)
  assert.equal(registry.profileFor('main'), 'abc-123')
  assert.equal(registry.labelForProfile('def'), 'profile-def')
  fs.rmSync(dir, { recursive: true, force: true })
})

test('registry drops duplicate and empty labels on load', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-registry-test-'))
  fs.writeFileSync(
    path.join(dir, 'windows.json'),
    JSON.stringify({
      windows: [
        { label: 'main', profile_id: 'a' },
        { label: 'main', profile_id: 'b' },
        { label: '', profile_id: 'c' },
      ],
    }),
  )
  const registry = new WindowRegistry(dir)
  assert.equal(registry.snapshot().length, 1)
  assert.equal(registry.profileFor('main'), 'a')
  fs.rmSync(dir, { recursive: true, force: true })
})

test('registry survives a corrupt file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-registry-test-'))
  fs.writeFileSync(path.join(dir, 'windows.json'), '{not json')
  const registry = new WindowRegistry(dir)
  assert.deepEqual(registry.snapshot(), [])
  fs.rmSync(dir, { recursive: true, force: true })
})

test('labels stay in a conservative charset', () => {
  assert.equal(profileWindowLabel('abc-123'), 'profile-abc-123')
  assert.equal(profileWindowLabel('we ird/id'), 'profile-we-ird-id')
})
