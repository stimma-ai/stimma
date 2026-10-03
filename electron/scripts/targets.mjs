// The esbuild entry points that make up the Electron shell. Shared by the
// production build (build.mjs) and the dev runner (dev.mjs) so dev never
// misses a bundle the shell loads at runtime.
import { join } from 'node:path'

export function shellTargets(root, overrides = {}) {
  const common = {
    bundle: true,
    platform: 'node',
    format: 'cjs',
    sourcemap: true,
    // electron and electron-updater stay external: electron is provided by the
    // runtime; electron-updater ships as a real dependency in node_modules.
    external: ['electron', 'electron-updater'],
    logLevel: 'info',
    loader: { '.txt': 'text' },
    ...overrides,
  }
  return [
    { ...common, entryPoints: [join(root, 'src', 'renderWorker.ts')], outfile: join(root, 'dist', 'render-worker.cjs') },
    { ...common, entryPoints: [join(root, 'src', 'main.ts')], outfile: join(root, 'dist', 'main.cjs') },
    { ...common, entryPoints: [join(root, 'src', 'preload.ts')], outfile: join(root, 'dist', 'preload.cjs') },
  ]
}
