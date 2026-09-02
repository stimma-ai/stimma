// Electron shell smoke test: main startup, first window, preload bridge, and
// clean quit. Runs the real main/preload build (dev mode, isolated sandbox)
// against a static server for the built frontend — no backend required.
//
// Run: node electron/tests/smoke.test.mjs   (from the repo root; requires
// `npm run build` in electron/ and a frontend build in frontend/dist)

import { createServer } from 'node:http'
import { createReadStream, existsSync } from 'node:fs'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { makeScratchDir } from './scratch.mjs'

const repoRoot = path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))))
const electronRoot = path.join(repoRoot, 'electron')
const distIndex = path.join(electronRoot, 'dist', 'main.cjs')
const frontendDist = path.join(repoRoot, 'frontend', 'dist')

const require = createRequire(path.join(repoRoot, 'frontend', 'package.json'))
const { _electron } = require('playwright')
const electronRequire = createRequire(path.join(electronRoot, 'package.json'))
const electronBinary = electronRequire('electron')

if (!existsSync(distIndex)) {
  console.error('electron/dist/main.cjs missing — run `npm run build` in electron/ first')
  process.exit(1)
}
if (!existsSync(path.join(frontendDist, 'index.html'))) {
  console.error('frontend/dist missing — run `npm run build` in frontend/ first')
  process.exit(1)
}

const MIME = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
  '.wasm': 'application/wasm',
}

const server = createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url || '/').split('?')[0])
  let file = path.join(frontendDist, urlPath === '/' ? 'index.html' : urlPath)
  if (!file.startsWith(frontendDist) || !existsSync(file)) {
    file = path.join(frontendDist, 'index.html') // SPA fallback
  }
  res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream')
  createReadStream(file).pipe(res)
})

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const port = server.address().port

const scratch = makeScratchDir('electron-smoke-')
const sandboxDir = scratch.dir
const fakeBackendPort = 9999

let failed = false
const check = (label, condition) => {
  if (condition) console.log(`ok - ${label}`)
  else {
    failed = true
    console.error(`FAIL - ${label}`)
  }
}

const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
const app = await _electron.launch({
  executablePath: electronBinary,
  args: [electronRoot],
  env: {
    ...env,
    STIMMA_DEV: '1',
    STIMMA_SANDBOX: 'smoke',
    STIMMA_DATA_DIR: path.join(sandboxDir, 'data'),
    STIMMA_CACHE_DIR: path.join(sandboxDir, 'cache'),
    STIMMA_BACKEND_PORT: String(fakeBackendPort),
    STIMMA_FRONTEND_PORT: String(port),
  },
})

try {
  const window = await app.firstWindow()
  await window.waitForLoadState('domcontentloaded')
  check('first window created and loaded', true)

  const title = await app.evaluate(({ BrowserWindow }) => {
    return BrowserWindow.getAllWindows()[0]?.getTitle() ?? null
  })
  check(`window title is Stimma (got: ${title})`, title === 'Stimma')

  const bridgeKind = await window.evaluate(() => window.stimmaDesktop?.kind ?? null)
  check(`preload bridge exposed (kind: ${bridgeKind})`, bridgeKind === 'electron')

  const appPort = await window.evaluate(() => window.stimmaDesktop.getBackendPort())
  check(
    `IPC round-trip: getBackendPort → local proxy ${appPort}`,
    Number.isInteger(appPort) && appPort > 0 && appPort <= 65535,
  )

  const logged = await window
    .evaluate(() => window.stimmaDesktop.log('info', 'smoke-test log line'))
    .then(() => true, () => false)
  check('IPC round-trip: log()', logged)

  const denied = await window
    .evaluate(() => window.open('https://example.com'))
    .then((handle) => handle === null, () => true)
  check('window.open denied', denied)
} finally {
  await app.close()
}

const shellLog = path.join(sandboxDir, 'data', 'Logs', 'Stimma-shell.log')
const logContents = existsSync(shellLog) ? fs.readFileSync(shellLog, 'utf8') : ''
check('shell log written with forwarded web line', logContents.includes('smoke-test log line'))

server.close()
scratch.cleanup()

if (failed) process.exit(1)
console.log('electron smoke: all checks passed')
