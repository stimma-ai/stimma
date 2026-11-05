import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { finished } from 'node:stream/promises'
import test from 'node:test'
import { RotatingLog } from '../src/rotatingLog.ts'

async function scratch(t: test.TestContext): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'shell-log-'))
  t.after(() => fs.rm(dir, { recursive: true, force: true }))
  return path.join(dir, 'Stimma-shell.log')
}

test('rotates queued stream writes into five bounded files in order', async (t) => {
  const filename = await scratch(t)
  const stream = new RotatingLog(filename, 16)
  for (let i = 0; i < 12; i++) stream.write(String(i).padStart(7, '0') + '\n')
  stream.end()
  await finished(stream)
  assert.equal((await fs.readdir(path.dirname(filename))).length, 5)
  for (let i = 0; i < 5; i++) assert.equal((await fs.stat(i ? `${filename}.${i}` : filename)).size, 16)
  assert.equal(await fs.readFile(filename, 'utf8'), '0000010\n0000011\n')
  assert.equal(await fs.readFile(filename + '.4', 'utf8'), '0000002\n0000003\n')
})

test('startup keeps only a bounded tail of a huge sparse legacy log before any write', async (t) => {
  const filename = await scratch(t)
  const file = await fs.open(filename, 'w')
  await file.write('\nrecent diagnostic\n', 1024 * 1024 * 1024)
  await file.close()
  const stream = new RotatingLog(filename, 32)
  stream.end()
  await finished(stream)
  assert.equal(await fs.readFile(filename, 'utf8'), 'recent diagnostic\n')
})

test('oversized records are discarded while later complete records survive', async (t) => {
  const filename = await scratch(t)
  const stream = new RotatingLog(filename, 16)
  stream.write('token=')
  stream.write('private-value '.repeat(20))
  stream.end('\ntail\n')
  await finished(stream)
  assert.equal(await fs.readFile(filename, 'utf8'), 'tail\n')
  for (const name of await fs.readdir(path.dirname(filename))) assert.ok((await fs.stat(path.join(path.dirname(filename), name))).size <= 16)
})

test('rotation keeps a secret assignment together across stream chunks', async (t) => {
  const filename = await scratch(t)
  const stream = new RotatingLog(filename, 32)
  stream.write('earlier record fills room\n')
  stream.write('token=')
  stream.end('private-value\n')
  await finished(stream)
  assert.equal(await fs.readFile(filename, 'utf8'), 'token=private-value\n')
  assert.equal(await fs.readFile(filename + '.1', 'utf8'), 'earlier record fills room\n')
})

test('legacy recovery discards a bounded fragment with no newline', async (t) => {
  const filename = await scratch(t)
  await fs.writeFile(filename, 'token=' + 'private-value '.repeat(20))
  const stream = new RotatingLog(filename, 32)
  stream.end()
  await finished(stream)
  assert.equal(await fs.readFile(filename, 'utf8'), '')
})

test('open and rotation IO errors never fail the writer or emit an unhandled error', async (t) => {
  const filename = await scratch(t)
  await fs.mkdir(filename)
  const stream = new RotatingLog(filename, 8192)
  stream.end('diagnostic')
  await finished(stream)
  await fs.rm(filename, { recursive: true })
  await fs.writeFile(filename, 'x'.repeat(8191) + '\n')
  await fs.mkdir(filename + '.4') // rm without recursive fails during rotation.
  const blocked = new RotatingLog(filename, 8192)
  blocked.end('diagnostic')
  await finished(blocked)
})

test('a rotation IO failure during writes is contained after the stream has opened', async (t) => {
  const filename = await scratch(t)
  const stream = new RotatingLog(filename, 8192)
  await new Promise<void>((resolve) => stream.write('x'.repeat(8191) + '\n', () => resolve()))
  await fs.mkdir(filename + '.4')
  stream.write('next diagnostic')
  stream.end('still usable')
  await finished(stream)
  assert.equal((await fs.stat(filename)).size, 8192)
})
