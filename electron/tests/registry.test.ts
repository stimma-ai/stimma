import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'
import fs from 'node:fs'
import path from 'node:path'

import { WindowRegistry, profileWindowLabel } from '../src/registry.ts'
import { makeScratchDir } from './scratch.mjs'

const scratchCleanups = new Set<() => void>()

function tmpDir(): string {
  const scratch = makeScratchDir('registry-test-')
  scratchCleanups.add(scratch.cleanup)
  return scratch.dir
}

afterEach(() => {
  for (const cleanup of scratchCleanups) cleanup()
  scratchCleanups.clear()
})

test('registry round-trips through disk', () => {
  const dir = tmpDir()

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
  const dir = tmpDir()
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
  const dir = tmpDir()
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
  const dir = tmpDir()
  fs.writeFileSync(path.join(dir, 'windows.json'), '{not json')
  const registry = new WindowRegistry(dir)
  assert.deepEqual(registry.snapshot(), [])
  fs.rmSync(dir, { recursive: true, force: true })
})

test('labels stay in a conservative charset', () => {
  assert.equal(profileWindowLabel('abc-123'), 'profile-abc-123')
  assert.equal(profileWindowLabel('we ird/id'), 'profile-we-ird-id')
})
