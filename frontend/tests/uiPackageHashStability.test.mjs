// Phones cache the server's UI package by content hash and download the whole
// archive on any change. Building the same UI source from a different commit
// must therefore produce the same package hash, with the commit carried in the
// manifest instead.
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('..', import.meta.url))
const repo = join(frontend, '..')
const vite = join(frontend, 'node_modules', 'vite', 'bin', 'vite.js')
const python = process.platform === 'win32' ? 'python' : 'python3'

function run(command, args, env = {}) {
  const result = spawnSync(command, args, {
    cwd: frontend, encoding: 'utf8', timeout: 240_000,
    env: { ...process.env, STIMMA_MOBILE_SHELL: '0', ...env },
  })
  assert.equal(result.status, 0, `${command} failed:\n${result.stdout}\n${result.stderr}`)
  return result.stdout
}

function files(directory, prefix = '') {
  return readdirSync(join(directory, prefix), { withFileTypes: true }).flatMap(entry => {
    const name = prefix ? `${prefix}/${entry.name}` : entry.name
    return entry.isDirectory() ? files(directory, name) : [name]
  })
}

test('UI package hash ignores the build commit', { timeout: 600_000 }, () => {
  const root = mkdtempSync(join(tmpdir(), 'stimma-ui-hash-'))
  try {
    const manifests = ['c0ffee1', 'decafe2'].map(commit => {
      const dist = join(root, `dist-${commit}`)
      run(process.execPath, [vite, 'build', '--outDir', dist, '--emptyOutDir', '--logLevel', 'error'],
        { STIMMA_BUILD_COMMIT: commit })
      assert.deepEqual(JSON.parse(readFileSync(join(dist, 'build-info.json'), 'utf8')), { commit })
      for (const name of files(dist)) {
        if (name === 'build-info.json') continue
        assert.ok(!readFileSync(join(dist, name)).includes(commit), `${name} embeds the build commit`)
      }
      return JSON.parse(run(python, [join(repo, 'tools', 'build_ui_package.py'), dist, join(root, `package-${commit}`)]))
    })
    assert.equal(manifests[0].hash, manifests[1].hash)
    assert.deepEqual(manifests.map(manifest => manifest.build), [{ commit: 'c0ffee1' }, { commit: 'decafe2' }])
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
