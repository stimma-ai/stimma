import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'

const built = await build({ configFile: false, logLevel: 'error',
  build: { write: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/storageMigration.ts', import.meta.url)), name: 'StorageMigrationTest', formats: ['iife'],
  } },
})
const code = (Array.isArray(built) ? built : [built]).flatMap(result => result.output).find(item => item.type === 'chunk').code
const DEBUG = 'ai.stimma.stimma.debug', CANARY = 'ai.stimma.stimma.canary'
const oldPrefix = `stimma_${DEBUG}_default_`, newPrefix = `stimma_${CANARY}_default_`

async function fixture(t) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  const warnings = []
  page.on('console', message => { if (message.type() === 'warning') warnings.push(message.text()) })
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<html></html>' }))
  await page.goto('http://storage.test/')
  await page.addScriptTag({ content: code })
  return { page, warnings }
}

async function migrate(page, sandbox = 'default', bundle = CANARY) {
  await page.evaluate(({ bundle, sandbox }) => window.storageMigration.migrateDebugScopedStorage(bundle, sandbox), { bundle, sandbox })
  if (bundle !== DEBUG) {
    await expect.poll(() => page.evaluate(key => localStorage.getItem(key), `stimma_${bundle}_${sandbox}_migrated_from_debug_blobs`)).toBe('1')
  }
}

test('migration renames UI keys and leaves unscoped state alone', async t => {
  const { page, warnings } = await fixture(t)
  await page.evaluate(({ DEBUG, oldPrefix }) => {
    localStorage.setItem(`${oldPrefix}global_sidebar`, '["a","b"]')
    localStorage.setItem(`${oldPrefix}p1_tool_flux_state`, '{"cfg":7}')
    localStorage.setItem('stimma_bundle_id', DEBUG)
  }, { DEBUG, oldPrefix })
  await migrate(page)
  assert.deepEqual(await page.evaluate(({ oldPrefix, newPrefix }) => [
    localStorage.getItem(`${newPrefix}global_sidebar`), localStorage.getItem(`${newPrefix}p1_tool_flux_state`),
    localStorage.getItem(`${oldPrefix}global_sidebar`), localStorage.getItem('stimma_bundle_id'),
    localStorage.getItem(`${newPrefix}migrated_from_debug`),
  ], { oldPrefix, newPrefix }), ['["a","b"]', '{"cfg":7}', null, DEBUG, '1'])
  assert.deepEqual(warnings, [])
})

test('migration never overwrites current UI keys or blobs', async t => {
  const { page, warnings } = await fixture(t)
  await page.evaluate(async ({ oldPrefix, newPrefix }) => {
    localStorage.setItem(`${oldPrefix}global_theme`, 'old')
    localStorage.setItem(`${newPrefix}global_theme`, 'new')
    await window.storageMigration.putBlob(`${oldPrefix}p1_mask`, { value: 'old' })
    await window.storageMigration.putBlob(`${newPrefix}p1_mask`, { value: 'new' })
  }, { oldPrefix, newPrefix })
  await migrate(page)
  assert.deepEqual(await page.evaluate(async ({ oldPrefix, newPrefix }) => ({
    theme: localStorage.getItem(`${newPrefix}global_theme`), oldTheme: localStorage.getItem(`${oldPrefix}global_theme`),
    blob: await window.storageMigration.getBlob(`${newPrefix}p1_mask`), oldBlob: await window.storageMigration.getBlob(`${oldPrefix}p1_mask`),
  }), { oldPrefix, newPrefix }), { theme: 'new', oldTheme: null, blob: { value: 'new' }, oldBlob: null })
  assert.deepEqual(warnings, [])
})

test('completion markers block later stale UI keys and blobs', async t => {
  const { page, warnings } = await fixture(t)
  await migrate(page)
  await page.evaluate(async ({ oldPrefix }) => {
    localStorage.setItem(`${oldPrefix}global_sidebar`, 'stale')
    await window.storageMigration.putBlob(`${oldPrefix}p1_mask`, 'stale')
  }, { oldPrefix })
  await migrate(page)
  assert.deepEqual(await page.evaluate(async ({ oldPrefix, newPrefix }) => [
    localStorage.getItem(`${newPrefix}global_sidebar`), localStorage.getItem(`${oldPrefix}global_sidebar`),
    await window.storageMigration.getBlob(`${newPrefix}p1_mask`), await window.storageMigration.getBlob(`${oldPrefix}p1_mask`),
  ], { oldPrefix, newPrefix }), [null, 'stale', null, 'stale'])
  assert.deepEqual(warnings, [])
})

test('debug installs retain their UI keys and IndexedDB blobs', async t => {
  const { page, warnings } = await fixture(t)
  await page.evaluate(async ({ oldPrefix }) => {
    localStorage.setItem(`${oldPrefix}global_sidebar`, 'x')
    await window.storageMigration.putBlob(`${oldPrefix}p1_mask`, 'pixels')
  }, { oldPrefix })
  await migrate(page, 'default', DEBUG)
  assert.deepEqual(await page.evaluate(async ({ oldPrefix }) => [
    localStorage.getItem(`${oldPrefix}global_sidebar`), await window.storageMigration.getBlob(`${oldPrefix}p1_mask`),
    localStorage.getItem(`${oldPrefix}migrated_from_debug`), localStorage.getItem(`${oldPrefix}migrated_from_debug_blobs`),
  ], { oldPrefix }), ['x', 'pixels', null, null])
  assert.deepEqual(warnings, [])
})

test('migration scopes both storage systems to the requested sandbox', async t => {
  const { page, warnings } = await fixture(t)
  await page.evaluate(async ({ DEBUG, oldPrefix }) => {
    localStorage.setItem(`${oldPrefix}global_sidebar`, 'default')
    localStorage.setItem(`stimma_${DEBUG}_other_global_sidebar`, 'other')
    await window.storageMigration.putBlob(`${oldPrefix}p1_mask`, 'default')
    await window.storageMigration.putBlob(`stimma_${DEBUG}_other_p1_mask`, 'other')
  }, { DEBUG, oldPrefix })
  await migrate(page, 'other')
  assert.deepEqual(await page.evaluate(async ({ DEBUG, CANARY, oldPrefix }) => [
    localStorage.getItem(`stimma_${CANARY}_other_global_sidebar`), localStorage.getItem(`${oldPrefix}global_sidebar`),
    await window.storageMigration.getBlob(`stimma_${CANARY}_other_p1_mask`), await window.storageMigration.getBlob(`${oldPrefix}p1_mask`),
    await window.storageMigration.getBlob(`stimma_${DEBUG}_other_p1_mask`),
  ], { DEBUG, CANARY, oldPrefix }), ['other', 'default', 'other', 'default', null])
  assert.deepEqual(warnings, [])
})

test('real IndexedDB migration preserves structured data and binary mask content', async t => {
  const { page, warnings } = await fixture(t)
  await page.evaluate(async ({ oldPrefix }) => {
    await window.storageMigration.putBlob(`${oldPrefix}p1_mask`, new Blob([new Uint8Array([0, 128, 255])], { type: 'image/png' }))
    await window.storageMigration.putBlob(`${oldPrefix}p1_paint`, { pixels: new Uint8Array([9, 8, 7]), version: 2 })
  }, { oldPrefix })
  await migrate(page)
  assert.deepEqual(await page.evaluate(async ({ oldPrefix, newPrefix }) => {
    const mask = await window.storageMigration.getBlob(`${newPrefix}p1_mask`)
    const paint = await window.storageMigration.getBlob(`${newPrefix}p1_paint`)
    return { mask: [...new Uint8Array(await mask.arrayBuffer())], type: mask.type,
      paint: { pixels: [...paint.pixels], version: paint.version }, remaining: await window.storageMigration.listBlobKeys(oldPrefix) }
  }, { oldPrefix, newPrefix }), { mask: [0, 128, 255], type: 'image/png', paint: { pixels: [9, 8, 7], version: 2 }, remaining: [] })
  assert.deepEqual(warnings, [])
})

test('a failed blob transaction leaves the completion marker unset and can resume', async t => {
  const { page, warnings } = await fixture(t)
  await page.evaluate(async ({ oldPrefix, CANARY }) => {
    const { putBlob, migrateDebugScopedStorage } = window.storageMigration
    await putBlob(`${oldPrefix}p1_a`, 'first')
    await putBlob(`${oldPrefix}p1_b`, 'second')
    const original = IDBDatabase.prototype.transaction
    let writes = 0
    IDBDatabase.prototype.transaction = function (...args) {
      // Copy/delete the first key, then fail the next copy. Keep all actual
      // reads/writes native; inject only one interrupted transaction boundary.
      if (args[1] === 'readwrite' && ++writes === 3) {
        IDBDatabase.prototype.transaction = original
        throw new DOMException('Injected interrupted write', 'QuotaExceededError')
      }
      return original.apply(this, args)
    }
    migrateDebugScopedStorage(CANARY, 'default')
  }, { oldPrefix, CANARY })
  await expect.poll(() => warnings.length).toBe(1)
  assert.match(warnings[0], /blob migration failed/)
  assert.deepEqual(await page.evaluate(async ({ oldPrefix, newPrefix }) => [
    localStorage.getItem(`${newPrefix}migrated_from_debug_blobs`),
    await window.storageMigration.getBlob(`${newPrefix}p1_a`), await window.storageMigration.getBlob(`${oldPrefix}p1_b`),
  ], { oldPrefix, newPrefix }), [null, 'first', 'second'])
  await migrate(page)
  assert.deepEqual(await page.evaluate(async ({ oldPrefix, newPrefix }) => [
    await window.storageMigration.getBlob(`${newPrefix}p1_a`), await window.storageMigration.getBlob(`${newPrefix}p1_b`),
    await window.storageMigration.listBlobKeys(oldPrefix),
  ], { oldPrefix, newPrefix }), ['first', 'second', []])
  assert.equal(warnings.length, 1)
})
