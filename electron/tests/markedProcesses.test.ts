import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { markedProcesses } from './markedProcesses.mjs'

test('Linux cleanup finds sanitized Chromium children and excludes nearby tests',
  { skip: process.platform !== 'linux', timeout: 10_000 }, async () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-process-test-'))
    const children: ReturnType<typeof spawn>[] = []
    const marker = `test-${process.pid}`
    async function child(root: string, env: NodeJS.ProcessEnv) {
      const proc = spawn(process.execPath,
        ['-e', "process.stdout.write('ready'); setInterval(() => {}, 1000)", '--',
          `--user-data-dir=${root}/chromium`], { env })
      children.push(proc)
      await once(proc.stdout!, 'data')
      return proc.pid!
    }
    try {
      const tagged = await child('/unrelated', { STIMMA_UPDATE_TEST_ID: marker })
      const sanitized = await child(scratch, {})
      const neighboring = await child(`${scratch}-other`, {})
      const found = markedProcesses(marker, scratch)
      assert.ok(found.includes(tagged))
      assert.ok(found.includes(sanitized))
      assert.ok(!found.includes(neighboring))
    } finally {
      await Promise.all(children.map(async proc => {
        const exited = once(proc, 'exit')
        proc.kill('SIGKILL')
        await exited
      }))
      fs.rmSync(scratch, { recursive: true, force: true })
    }
  })
