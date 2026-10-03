// Bundle the Electron main process, preload script and render worker with esbuild.
// All CJS: main is the Electron entry, preload must be CJS when sandboxed.
import { build, context } from 'esbuild'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'
import { shellTargets } from './targets.mjs'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const watch = process.argv.includes('--watch')

const targets = shellTargets(root)

if (watch) {
  const contexts = await Promise.all(targets.map((t) => context(t)))
  await Promise.all(contexts.map((c) => c.watch()))
  console.log('[electron-build] watching for changes...')
} else {
  await Promise.all(targets.map((t) => build(t)))
}
