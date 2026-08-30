// Development runner: esbuild watch over main/preload + automatic Electron
// restart when either rebuilds. Renderer changes never pass through here —
// Vite HMR owns those. The backend is external in dev (STIMMA_DEV=1).
import { context } from 'esbuild'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const require = createRequire(import.meta.url)
const electronBinary = require('electron')

let child = null
let restartTimer = null
let shuttingDown = false

// A parent environment that sets ELECTRON_RUN_AS_NODE (some editor/agent
// shells do) would silently turn Electron into plain Node — scrub it.
const childEnv = { ...process.env }
delete childEnv.ELECTRON_RUN_AS_NODE

function startElectron() {
  child = spawn(electronBinary, [root], {
    stdio: 'inherit',
    env: childEnv,
  })
  child.on('exit', (code) => {
    if (shuttingDown) return
    if (restartTimer === null) {
      // Electron exited on its own (window closed / crash) — end the runner.
      process.exit(code ?? 0)
    }
  })
}

function scheduleRestart() {
  if (restartTimer) clearTimeout(restartTimer)
  restartTimer = setTimeout(() => {
    console.log('[electron-dev] main/preload changed; restarting shell...')
    const previous = child
    if (previous && previous.exitCode === null) {
      previous.removeAllListeners('exit')
      previous.once('exit', () => {
        restartTimer = null
        startElectron()
      })
      previous.kill('SIGTERM')
    } else {
      restartTimer = null
      startElectron()
    }
  }, 150)
}

const common = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  sourcemap: true,
  external: ['electron', 'electron-updater'],
  logLevel: 'warning',
}

// watch() performs one initial build per context; only rebuilds after that
// should restart the shell. Launch waits for both initial builds.
let initialBuildsRemaining = 2
let resolveInitialBuilds
const initialBuilds = new Promise((resolve) => { resolveInitialBuilds = resolve })
const notify = {
  name: 'restart-on-rebuild',
  setup(build) {
    build.onEnd((result) => {
      if (result.errors.length > 0) return
      if (initialBuildsRemaining > 0) {
        initialBuildsRemaining--
        if (initialBuildsRemaining === 0) resolveInitialBuilds()
        return
      }
      scheduleRestart()
    })
  },
}

const contexts = await Promise.all([
  context({
    ...common,
    entryPoints: [join(root, 'src', 'main.ts')],
    outfile: join(root, 'dist', 'main.cjs'),
    plugins: [notify],
  }),
  context({
    ...common,
    entryPoints: [join(root, 'src', 'preload.ts')],
    outfile: join(root, 'dist', 'preload.cjs'),
    plugins: [notify],
  }),
])

await Promise.all(contexts.map((c) => c.watch()))
await initialBuilds
console.log('[electron-dev] shell built; launching Electron (watching main/preload)...')
startElectron()

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    shuttingDown = true
    if (child && child.exitCode === null) child.kill('SIGTERM')
    process.exit(signal === 'SIGINT' ? 130 : 143)
  })
}
