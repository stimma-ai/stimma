import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { DRAG_CACHE_MAX_AGE_MS, cacheDragFile, pruneDragCache } from '../src/dragCache.ts'

const dirs: string[] = []
function tempDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'drag-cache-test-'))
  dirs.push(dir)
  return dir
}
test.after(() => {
  for (const dir of dirs) fs.rmSync(dir, { recursive: true, force: true })
})

test('repeat drags of the same file reuse one copy', async () => {
  const dir = tempDir()
  const data = new TextEncoder().encode('pixels')
  const first = await cacheDragFile(dir, 'shot.png', data)
  const second = await cacheDragFile(dir, 'shot.png', data)
  assert.equal(first, second)
  assert.equal(path.basename(first), 'shot.png')
  assert.equal(fs.readFileSync(first, 'utf8'), 'pixels')
  assert.equal(fs.readdirSync(path.join(dir, 'stimma-drag')).length, 1)
  const other = await cacheDragFile(dir, 'shot.png', new TextEncoder().encode('other'))
  assert.notEqual(other, first)
})

test('rejects filenames that escape the cache', async () => {
  const dir = tempDir()
  const target = await cacheDragFile(dir, '../../etc/passwd', new Uint8Array([1]))
  assert.ok(target.startsWith(path.join(dir, 'stimma-drag')))
  await assert.rejects(cacheDragFile(dir, '..', new Uint8Array([1])), /Invalid/)
})

test('prunes stale copies and legacy per-drag directories, keeps fresh ones', async () => {
  const dir = tempDir()
  const fresh = await cacheDragFile(dir, 'fresh.png', new Uint8Array([1]))
  const stale = await cacheDragFile(dir, 'stale.png', new Uint8Array([2]))
  const legacy = path.join(dir, 'stimma-drag-AbC123')
  fs.mkdirSync(legacy)
  fs.writeFileSync(path.join(legacy, 'old.mp4'), 'x')
  const unrelated = path.join(dir, 'something-else')
  fs.mkdirSync(unrelated)
  const old = new Date(Date.now() - DRAG_CACHE_MAX_AGE_MS - 60_000)
  for (const p of [path.dirname(stale), legacy, unrelated]) fs.utimesSync(p, old, old)

  await pruneDragCache(dir)

  assert.ok(fs.existsSync(fresh))
  assert.ok(!fs.existsSync(path.dirname(stale)))
  assert.ok(!fs.existsSync(legacy))
  assert.ok(fs.existsSync(unrelated))
})
