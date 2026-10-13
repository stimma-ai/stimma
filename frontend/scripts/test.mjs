import { readdirSync } from 'node:fs'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))

function testFiles(directory) {
  return readdirSync(join(root, directory), { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return testFiles(path)
    return /\.test\.(?:js|ts|mjs)$/.test(entry.name) ? [path] : []
  })
}

// Discover unit and browser regressions together; acceptance specs have their
// own backend lifecycle and stay under `stimma test acceptance`.
const files = ['src', 'tests'].flatMap(testFiles).sort()
console.log(`Running ${files.length} frontend test files`)
const result = spawnSync(process.execPath, [
  '--test', '--experimental-strip-types', '--test-concurrency=4',
  ...process.argv.slice(2), ...files,
], { cwd: root, stdio: 'inherit' })
if (result.error) throw result.error
process.exit(result.status ?? 1)
