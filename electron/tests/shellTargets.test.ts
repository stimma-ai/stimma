import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { shellTargets } from '../scripts/targets.mjs'

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)))

test('shell targets include the render worker the main process loads', () => {
  const outfiles = shellTargets(root).map((t) => path.basename(t.outfile))
  assert.deepEqual(outfiles.sort(), ['main.cjs', 'preload.cjs', 'render-worker.cjs'])
})

test('dev runner and production build share the same target list', () => {
  for (const script of ['dev.mjs', 'build.mjs']) {
    const source = fs.readFileSync(path.join(root, 'scripts', script), 'utf8')
    assert.match(source, /shellTargets\(root/, `${script} must build from shellTargets()`)
    assert.doesNotMatch(source, /entryPoints:/, `${script} must not declare its own entry points`)
  }
})
