// Bundle the Electron main process and preload script with esbuild.
// Main is CJS (Electron entry), preload is CJS (sandboxed preload requirement).
import { build, context } from 'esbuild'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const watch = process.argv.includes('--watch')

const common = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  sourcemap: true,
  // electron and electron-updater stay external: electron is provided by the
  // runtime; electron-updater ships as a real dependency in node_modules.
  external: ['electron', 'electron-updater'],
  logLevel: 'info',
}

const targets = [
  {
    ...common,
    entryPoints: [join(root, 'src', 'main.ts')],
    outfile: join(root, 'dist', 'main.cjs'),
  },
  {
    ...common,
    entryPoints: [join(root, 'src', 'preload.ts')],
    outfile: join(root, 'dist', 'preload.cjs'),
  },
]

if (watch) {
  const contexts = await Promise.all(targets.map((t) => context(t)))
  await Promise.all(contexts.map((c) => c.watch()))
  console.log('[electron-build] watching for changes...')
} else {
  await Promise.all(targets.map((t) => build(t)))
}
