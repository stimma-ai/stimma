import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { migrateDebugScopedStorage } from './debugPrefixMigration.ts'

// Minimal localStorage stub for node:test.
class MemoryStorage {
  private map = new Map<string, string>()
  get length() { return this.map.size }
  key(i: number) { return [...this.map.keys()][i] ?? null }
  getItem(k: string) { return this.map.has(k) ? this.map.get(k)! : null }
  setItem(k: string, v: string) { this.map.set(k, String(v)) }
  removeItem(k: string) { this.map.delete(k) }
  clear() { this.map.clear() }
}

const storage = new MemoryStorage()
;(globalThis as Record<string, unknown>).localStorage = storage

const DEBUG = 'ai.stimma.stimma.debug'
const CANARY = 'ai.stimma.stimma.canary'

beforeEach(() => storage.clear())

test('renames debug-scoped keys to the current bundle prefix', () => {
  storage.setItem(`stimma_${DEBUG}_default_global_sidebar`, '["a","b"]')
  storage.setItem(`stimma_${DEBUG}_default_p1_tool_flux_state`, '{"cfg":7}')
  storage.setItem('stimma_bundle_id', DEBUG) // unscoped keys untouched

  migrateDebugScopedStorage(CANARY, 'default')

  assert.equal(storage.getItem(`stimma_${CANARY}_default_global_sidebar`), '["a","b"]')
  assert.equal(storage.getItem(`stimma_${CANARY}_default_p1_tool_flux_state`), '{"cfg":7}')
  assert.equal(storage.getItem(`stimma_${DEBUG}_default_global_sidebar`), null)
  assert.equal(storage.getItem('stimma_bundle_id'), DEBUG)
  assert.equal(storage.getItem(`stimma_${CANARY}_default_migrated_from_debug`), '1')
})

test('never overwrites keys already written under the new prefix', () => {
  storage.setItem(`stimma_${DEBUG}_default_global_theme`, 'old')
  storage.setItem(`stimma_${CANARY}_default_global_theme`, 'new')

  migrateDebugScopedStorage(CANARY, 'default')

  assert.equal(storage.getItem(`stimma_${CANARY}_default_global_theme`), 'new')
  assert.equal(storage.getItem(`stimma_${DEBUG}_default_global_theme`), null)
})

test('runs once — marker blocks later stale debug keys', () => {
  migrateDebugScopedStorage(CANARY, 'default')
  storage.setItem(`stimma_${DEBUG}_default_global_sidebar`, 'stale')

  migrateDebugScopedStorage(CANARY, 'default')

  assert.equal(storage.getItem(`stimma_${CANARY}_default_global_sidebar`), null)
  assert.equal(storage.getItem(`stimma_${DEBUG}_default_global_sidebar`), 'stale')
})

test('no-op on the debug bundle itself', () => {
  storage.setItem(`stimma_${DEBUG}_default_global_sidebar`, 'x')

  migrateDebugScopedStorage(DEBUG, 'default')

  assert.equal(storage.getItem(`stimma_${DEBUG}_default_global_sidebar`), 'x')
  assert.equal(storage.getItem(`stimma_${DEBUG}_default_migrated_from_debug`), null)
})

test('respects sandbox scoping', () => {
  storage.setItem(`stimma_${DEBUG}_default_global_sidebar`, 'default-sb')
  storage.setItem(`stimma_${DEBUG}_other_global_sidebar`, 'other-sb')

  migrateDebugScopedStorage(CANARY, 'other')

  assert.equal(storage.getItem(`stimma_${CANARY}_other_global_sidebar`), 'other-sb')
  assert.equal(storage.getItem(`stimma_${DEBUG}_default_global_sidebar`), 'default-sb')
})
