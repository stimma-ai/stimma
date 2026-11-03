import assert from 'node:assert/strict'
import type { ChildProcess } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import test from 'node:test'
import { observeBackendOutput, parseBackendPort } from '../src/backendOutput.ts'

function fixture() {
  const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() })
  const ports: number[] = []
  const diagnostics: string[] = []
  const consoleOutput: string[] = []
  const save = observeBackendOutput(child as unknown as ChildProcess, {
    port: (port) => ports.push(port),
    output: (chunk) => consoleOutput.push(chunk.toString()),
    diagnostic: (text) => diagnostics.push(text),
  })
  return { child, ports, diagnostics, consoleOutput, save }
}

test('backend output and split port announcements stay live without shell log duplication', () => {
  const f = fixture()
  f.child.stdout.write('routine output\nSTIMMA_BACKEND_PO')
  f.child.stdout.write('RT=9191\n')
  f.child.stderr.write('routine warning\n')
  assert.deepEqual(f.ports, [9191])
  assert.equal(f.consoleOutput.length, 3)
  assert.deepEqual(f.diagnostics, [])
  f.child.emit('close', 0, null)
  assert.deepEqual(f.diagnostics, [])
  assert.equal(parseBackendPort('STIMMA_BACKEND_PORT=65536'), null)
})

test('abnormal exit preserves at most 64 KiB including final stderr', () => {
  const f = fixture()
  f.child.stdout.write('old output\n' + 'x'.repeat(100_000) + '\n')
  f.child.emit('exit', 1, null)
  f.child.stderr.end('final traceback before logger opened\n')
  f.child.emit('close', 1, null)
  assert.equal(f.diagnostics.length, 1)
  assert.ok(Buffer.byteLength(f.diagnostics[0]) <= 64 * 1024)
  assert.ok(f.diagnostics[0].endsWith('final traceback before logger opened\n'))
  assert.ok(!f.diagnostics[0].includes('old output'))
})

test('watchdog restarts preserve crash diagnostics even if the next backend succeeds', () => {
  const f = fixture()
  f.child.stderr.write('native crash traceback\n[watchdog] Backend crashed: signal 11\n')
  f.child.stdout.write('STIMMA_BACKEND_PORT=9191\n')
  f.child.emit('close', 0, null)
  assert.equal(f.diagnostics.length, 1)
  assert.match(f.diagnostics[0], /native crash traceback/)
})

test('startup failures, spawn errors and startup timeouts retain the only output', () => {
  for (const event of ['clean-early-exit', 'error', 'timeout']) {
    const f = fixture()
    f.child.stderr.write('cannot initialize logger\n')
    if (event === 'error') f.child.emit('error', new Error('spawn failed'))
    else if (event === 'timeout') f.save()
    else f.child.emit('close', 0, null)
    assert.match(f.diagnostics[0], /cannot initialize logger/)
  }
})
