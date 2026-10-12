import test from 'node:test'
import assert from 'node:assert/strict'
import { exportPathSegments, uniqueNameCandidates } from './exportPaths.ts'

test('export entry names split into plain segments', () => {
  assert.deepEqual(exportPathSegments('walk/frame-01.png'), ['walk', 'frame-01.png'])
  assert.deepEqual(exportPathSegments('a\\b.png'), ['a', 'b.png'])
})

test('export entry names cannot leave the chosen folder', () => {
  assert.throws(() => exportPathSegments('../escape.png'))
  assert.throws(() => exportPathSegments('walk/../../escape.png'))
  assert.throws(() => exportPathSegments('/etc/passwd'))
  assert.throws(() => exportPathSegments('C:\\Windows\\x.dll'))
  assert.throws(() => exportPathSegments(''))
})

test('unique names number before the extension, folders keep their whole name', () => {
  const files = uniqueNameCandidates('harbor.jpg')
  assert.equal(files.next().value, 'harbor.jpg')
  assert.equal(files.next().value, 'harbor (1).jpg')
  const folders = uniqueNameCandidates('knight-godot.v2', true)
  folders.next()
  assert.equal(folders.next().value, 'knight-godot.v2 (1)')
})
