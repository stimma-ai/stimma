import assert from 'node:assert/strict'
import test from 'node:test'
import { parsePythonRuntimeArchive, selectPythonRuntimeArchive } from '../src/pythonRuntimeName.ts'

test('runtime archive names carry an exact SHA-256 identity', () => {
  const digest = 'a'.repeat(64)
  assert.equal(parsePythonRuntimeArchive(`stimma-python-runtime-${digest}.tar.xz`), digest)
  assert.equal(parsePythonRuntimeArchive(`stimma-python-runtime-${digest}.tar.xz.tmp`), null)
  assert.equal(parsePythonRuntimeArchive('stimma-python-runtime-not-a-hash.tar.xz'), null)
})

test('uses this build runtime even when a failed uninstall left older archives', () => {
  const older = `stimma-python-runtime-${'a'.repeat(64)}.tar.xz`
  const current = `stimma-python-runtime-${'b'.repeat(64)}.tar.xz`
  assert.deepEqual(selectPythonRuntimeArchive([older, current], current), { name: current, sha256: 'b'.repeat(64) })
  assert.throws(() => selectPythonRuntimeArchive([older], current), /missing/)
  assert.throws(() => selectPythonRuntimeArchive([older], '../escape.tar.xz'), /Invalid/)
  assert.equal(selectPythonRuntimeArchive(['app.asar']), null)
  assert.deepEqual(selectPythonRuntimeArchive([older]), { name: older, sha256: 'a'.repeat(64) })
})
