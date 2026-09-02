import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import {
  appCacheRoot,
  hasStagedPackage,
  pendingUpdateDir,
  pruneStagedUpdate,
  readStagedUpdate,
  readUpdaterCacheDirName,
} from '../src/updaterCache.ts'

function scratch(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'updater-cache-'))
}

function stage(dir: string, fileName: string, withPackage: boolean): string {
  const pending = path.join(dir, 'pending')
  fs.mkdirSync(pending, { recursive: true })
  fs.writeFileSync(
    path.join(pending, 'update-info.json'),
    JSON.stringify({ fileName, sha512: 'x', isAdminRightsRequired: false }),
  )
  if (withPackage) fs.writeFileSync(path.join(pending, fileName), 'package')
  return pending
}

test('a descriptor left behind by a completed install is pruned', () => {
  // The production failure: installing moves the package out of pending/ but
  // electron-updater's "Cached update file doesn't exist" branch returns
  // without cleaning, so update-info.json outlives the package for good.
  const pending = stage(scratch(), 'Stimma Canary-1.0.14-canary.845.AppImage', false)

  assert.equal(hasStagedPackage(pending), false)
  assert.equal(pruneStagedUpdate(pending), 'Stimma Canary-1.0.14-canary.845.AppImage')
  assert.equal(fs.existsSync(path.join(pending, 'update-info.json')), false)
  // Idempotent: nothing left to prune on the next launch.
  assert.equal(pruneStagedUpdate(pending), null)
})

test('a genuinely staged package is left alone', () => {
  const pending = stage(scratch(), 'Stimma Canary-1.0.14-canary.847.AppImage', true)

  assert.equal(hasStagedPackage(pending), true)
  assert.equal(pruneStagedUpdate(pending), null)
  assert.equal(fs.existsSync(path.join(pending, 'update-info.json')), true)
})

test('no staged update at all is not an error', () => {
  const pending = path.join(scratch(), 'pending')
  fs.mkdirSync(pending, { recursive: true })

  assert.equal(readStagedUpdate(pending), null)
  assert.equal(hasStagedPackage(pending), false)
  assert.equal(pruneStagedUpdate(pending), null)
})

test('a descriptor escaping the pending directory is refused', () => {
  // readStagedUpdate feeds an unlink-then-move install; a traversing fileName
  // must never resolve to a path outside pending/.
  const pending = stage(scratch(), '../../evil.AppImage', true)

  assert.equal(readStagedUpdate(pending), null)
  assert.equal(hasStagedPackage(pending), false)
})

test('a corrupt descriptor is left for electron-updater to clean', () => {
  const dir = scratch()
  const pending = path.join(dir, 'pending')
  fs.mkdirSync(pending, { recursive: true })
  fs.writeFileSync(path.join(pending, 'update-info.json'), 'not json')

  assert.equal(readStagedUpdate(pending), null)
  assert.equal(pruneStagedUpdate(pending), null)
  assert.equal(fs.existsSync(path.join(pending, 'update-info.json')), true)
})

test('updaterCacheDirName is read out of app-update.yml', () => {
  const dir = scratch()
  const yml = path.join(dir, 'app-update.yml')
  fs.writeFileSync(
    yml,
    [
      'provider: generic',
      'url: https://updates.example.test/stimma/canary/linux-x86_64',
      'channel: canary',
      'updaterCacheDirName: stimma-shell-updater',
      '',
    ].join('\n'),
  )

  assert.equal(readUpdaterCacheDirName(yml), 'stimma-shell-updater')
  assert.equal(readUpdaterCacheDirName(path.join(dir, 'missing.yml')), null)
})

test('the cache root matches electron-updater per platform', () => {
  assert.equal(
    pendingUpdateDir('stimma-shell-updater', '/c'),
    path.join('/c', 'stimma-shell-updater', 'pending'),
  )
  assert.equal(appCacheRoot('linux', { XDG_CACHE_HOME: '/xdg' }, '/home/u'), '/xdg')
  assert.equal(appCacheRoot('linux', {}, '/home/u'), path.join('/home/u', '.cache'))
  assert.equal(appCacheRoot('darwin', {}, '/home/u'), path.join('/home/u', 'Library', 'Caches'))
  assert.equal(
    appCacheRoot('win32', {}, '/home/u'),
    path.join('/home/u', 'AppData', 'Local'),
  )
})
