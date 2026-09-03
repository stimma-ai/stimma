import assert from 'node:assert/strict'
import test from 'node:test'

import {
  activeRootFor,
  basename,
  crumbsFor,
  crumbsFromPath,
  groupRoots,
  isSameOrDescendant,
  parseRecents,
  pushRecent,
  recentsStorageKey,
  type DirectoryEntry,
} from './directoryPicker.ts'

test('basename handles posix, windows, trailing separators and bare roots', () => {
  assert.equal(basename('/home/someone/Pictures'), 'Pictures')
  assert.equal(basename('/home/someone/Pictures/'), 'Pictures')
  assert.equal(basename('C:\\Users\\Someone\\Videos'), 'Videos')
  assert.equal(basename('C:\\'), 'C:')
  assert.equal(basename('/'), '/')
})

test('isSameOrDescendant does not match sibling prefixes', () => {
  assert.equal(isSameOrDescendant('/data', '/data'), true)
  assert.equal(isSameOrDescendant('/data/photos', '/data'), true)
  assert.equal(isSameOrDescendant('/database', '/data'), false)
  assert.equal(isSameOrDescendant('/', '/'), true)
  assert.equal(isSameOrDescendant('/srv', '/'), true)
  assert.equal(isSameOrDescendant('C:\\Users\\Me', 'C:\\'), true)
  assert.equal(isSameOrDescendant('D:\\Users', 'C:\\'), false)
})

test('activeRootFor prefers the longest containing root', () => {
  const roots: DirectoryEntry[] = [
    { name: 'Home', path: '/home/someone', is_dir: true, kind: 'home' },
    { name: 'Pictures', path: '/home/someone/Pictures', is_dir: true, kind: 'place' },
    { name: 'Filesystem', path: '/', is_dir: true, kind: 'volume' },
  ]
  assert.equal(activeRootFor('/home/someone/Pictures/2024', roots), '/home/someone/Pictures')
  assert.equal(activeRootFor('/home/someone/Documents', roots), '/home/someone')
  assert.equal(activeRootFor('/srv/media', roots), '/')
  assert.equal(activeRootFor('', roots), null)
})

test('crumbsFromPath walks posix paths from the root', () => {
  assert.deepEqual(crumbsFromPath('/srv/media/raw'), [
    { name: '/', path: '/' },
    { name: 'srv', path: '/srv' },
    { name: 'media', path: '/srv/media' },
    { name: 'raw', path: '/srv/media/raw' },
  ])
})

test('crumbsFromPath keeps the windows drive letter as the first crumb', () => {
  assert.deepEqual(crumbsFromPath('C:\\Users\\Someone'), [
    { name: 'C:', path: 'C:\\' },
    { name: 'Users', path: 'C:\\Users' },
    { name: 'Someone', path: 'C:\\Users\\Someone' },
  ])
})

test('crumbsFor prefers server segments and is empty at the roots listing', () => {
  const segments = [{ name: 'Home', path: '/home/someone' }]
  assert.deepEqual(crumbsFor({ path: '/home/someone', parent: '/home', segments, entries: [] }), segments)
  assert.deepEqual(crumbsFor({ path: '/x/y', parent: '/x', segments: [], entries: [] }), crumbsFromPath('/x/y'))
  assert.deepEqual(crumbsFor({ path: '', parent: null, segments: [], entries: [] }), [])
  assert.deepEqual(crumbsFor(null), [])
})

test('groupRoots drops empty groups and buckets kind-less roots as Locations', () => {
  const groups = groupRoots([
    { name: 'Home', path: '/h', is_dir: true, kind: 'home' },
    { name: 'Old', path: '/o', is_dir: true },
  ])
  assert.deepEqual(groups.map((g) => g.label), ['Places', 'Locations'])
  assert.deepEqual(groups[0].roots.map((r) => r.name), ['Home'])
})

test('pushRecent de-duplicates, orders newest first, and caps the list', () => {
  let recents = pushRecent([], '/a/one')
  recents = pushRecent(recents, '/a/two')
  recents = pushRecent(recents, '/a/one')
  assert.deepEqual(recents.map((r) => r.path), ['/a/one', '/a/two'])
  assert.equal(recents[0].name, 'one')

  for (const p of ['/b/1', '/b/2', '/b/3', '/b/4', '/b/5']) recents = pushRecent(recents, p)
  assert.equal(recents.length, 4)
  assert.equal(recents[0].path, '/b/5')
})

test('parseRecents tolerates garbage and fills in missing names', () => {
  assert.deepEqual(parseRecents(null), [])
  assert.deepEqual(parseRecents('not json'), [])
  assert.deepEqual(parseRecents('{"path":"/x"}'), [])
  assert.deepEqual(parseRecents('[{"path":"/x/y"},{"nope":1},{"name":"n","path":"/z"}]'), [
    { name: 'y', path: '/x/y' },
    { name: 'n', path: '/z' },
  ])
})

test('recents are scoped per server', () => {
  assert.equal(recentsStorageKey(null), 'stimma_folder_picker_recents:local')
  assert.equal(recentsStorageKey('local'), 'stimma_folder_picker_recents:local')
  assert.equal(recentsStorageKey('dev-123'), 'stimma_folder_picker_recents:dev-123')
})
