import assert from 'node:assert/strict'
import test from 'node:test'
import { parsePythonRuntimeArchive } from '../src/pythonRuntimeName.ts'

test('runtime archive names carry an exact SHA-256 identity', () => {
  const digest = 'a'.repeat(64)
  assert.equal(parsePythonRuntimeArchive(`stimma-python-runtime-${digest}.tar.xz`), digest)
  assert.equal(parsePythonRuntimeArchive(`stimma-python-runtime-${digest}.tar.xz.tmp`), null)
  assert.equal(parsePythonRuntimeArchive('stimma-python-runtime-not-a-hash.tar.xz'), null)
})
