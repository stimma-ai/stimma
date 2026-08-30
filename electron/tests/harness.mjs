// Shared launch harness for Electron e2e tests: static server over the built
// frontend, isolated temp sandbox, Playwright _electron driver.
import { createServer } from 'node:http'
import { createReadStream, existsSync } from 'node:fs'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

export const repoRoot = path.dirname(
  path.dirname(path.dirname(fileURLToPath(import.meta.url))),
)
export const electronRoot = path.join(repoRoot, 'electron')
const frontendDist = path.join(repoRoot, 'frontend', 'dist')

const frontendRequire = createRequire(path.join(repoRoot, 'frontend', 'package.json'))
export const { _electron } = frontendRequire('playwright')
const electronRequire = createRequire(path.join(electronRoot, 'package.json'))
export const electronBinary = electronRequire('electron')

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

export function assertPrereqs() {
  if (!existsSync(path.join(electronRoot, 'dist', 'main.cjs'))) {
    throw new Error('electron/dist/main.cjs missing — run `npm run build` in electron/')
  }
  if (!existsSync(path.join(frontendDist, 'index.html'))) {
    throw new Error('frontend/dist missing — run `npm run build` in frontend/')
  }
}

export async function startFrontendServer() {
  const server = createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || '/').split('?')[0])
    let file = path.join(frontendDist, urlPath === '/' ? 'index.html' : urlPath)
    if (!file.startsWith(frontendDist) || !existsSync(file)) {
      file = path.join(frontendDist, 'index.html')
    }
    res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream')
    createReadStream(file).pipe(res)
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  return { server, port: server.address().port }
}

export function makeSandbox() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-electron-test-'))
  return {
    dir,
    dataDir: path.join(dir, 'data'),
    cacheDir: path.join(dir, 'cache'),
    cleanup: () => fs.rmSync(dir, { recursive: true, force: true }),
  }
}

export async function launchShell({ sandbox, frontendPort, backendPort = 9999 }) {
  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE
  return _electron.launch({
    executablePath: electronBinary,
    args: [electronRoot],
    env: {
      ...env,
      STIMMA_DEV: '1',
      STIMMA_SANDBOX: 'e2e',
      STIMMA_DATA_DIR: sandbox.dataDir,
      STIMMA_CACHE_DIR: sandbox.cacheDir,
      STIMMA_BACKEND_PORT: String(backendPort),
      STIMMA_FRONTEND_PORT: String(frontendPort),
    },
  })
}
