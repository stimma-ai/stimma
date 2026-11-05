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
const discovered = ['src', 'tests'].flatMap(testFiles).sort()
const args = process.argv.slice(2)
const normalize = path => path.replaceAll('\\', '/').replace(/^\.\//, '')
const requested = args.filter(arg => arg.startsWith('--file=')).map(arg => normalize(arg.slice('--file='.length)))
for (const path of requested) {
  if (!discovered.some(file => normalize(file) === path)) throw new Error(`Unknown frontend test file: ${path}`)
}
const files = requested.length ? discovered.filter(file => requested.includes(normalize(file))) : discovered
if (args.includes('--list')) {
  console.log(files.join('\n'))
  process.exit(0)
}
console.log(`Running ${files.length} frontend test files`)
const result = spawnSync(process.execPath, [
  '--test', '--experimental-strip-types', '--test-concurrency=4',
  ...args.filter(arg => !arg.startsWith('--file=')), ...files,
], { cwd: root, stdio: 'inherit' })
if (result.error) throw result.error
process.exit(result.status ?? 1)
