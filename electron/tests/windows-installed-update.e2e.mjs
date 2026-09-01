// Real installed-NSIS updater test. Requires two prebuilt versions: the older
// version installed at the Tauri-compatible path, and the newer installer plus
// manifest in electron/out. Uses Chrome DevTools Protocol instead of
// Playwright's Electron loader so the packaged app runs exactly as production.

import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createReadStream, existsSync, mkdtempSync, readFileSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

if (process.platform !== 'win32') throw new Error('Windows only')

const electronRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repoRoot = path.dirname(electronRoot)
const require = createRequire(path.join(repoRoot, 'frontend', 'package.json'))
const { chromium } = require('playwright')
const electronBinary = createRequire(path.join(electronRoot, 'package.json'))('electron')
const installedExe = process.argv[2]
const feedDir = process.argv[3]
const expectedVersion = process.argv[4]
if (!installedExe || !feedDir || !expectedVersion) {
  throw new Error('usage: node windows-installed-update.e2e.mjs <installed.exe> <feed-dir> <expected-version>')
}

const work = mkdtempSync(path.join(os.tmpdir(), 'stimma-windows-update-'))
const dataDir = path.join(work, 'data')
const cacheDir = path.join(work, 'cache')
const prefix = '/stimma/canary/windows-x86_64/'

// Seed the real WebView2 layout so this updater run also verifies the
// Tauri-to-Electron localStorage handoff in the installed application.
const fixtureRows = [
  ['profileId', 'profile-windows-update-test'],
  ['stimma_bundle_id', 'ai.stimma.stimma.canary'],
  ['stimma_global_theme', 'dark'],
]
const fixture = spawnSync(electronBinary, [
  path.join(electronRoot, 'tests', 'write-chromium-storage-fixture.cjs'),
  path.join(dataDir, 'browser', 'EBWebView', 'Default'),
  Buffer.from(JSON.stringify(fixtureRows)).toString('base64'),
], { env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined }, stdio: 'inherit' })
assert.equal(fixture.status, 0, 'WebView2 fixture writer failed')

const server = createServer((req, res) => {
  const pathname = decodeURIComponent((req.url || '/').split('?')[0])
  if (!pathname.startsWith(prefix)) return void res.writeHead(404).end()
  const name = pathname.slice(prefix.length)
  if (!name || name !== path.basename(name)) return void res.writeHead(400).end()
  const file = path.join(feedDir, name === 'latest.yml' ? 'canary.yml' : name)
  if (!existsSync(file)) return void res.writeHead(404).end()
  const stat = statSync(file)
  res.writeHead(200, {
    'Content-Length': stat.size,
    'Content-Type': name.endsWith('.yml') ? 'text/yaml' : 'application/octet-stream',
  })
  if (req.method === 'HEAD') res.end()
  else createReadStream(file).pipe(res)
})
await new Promise((resolve, reject) => {
  server.once('error', reject)
  server.listen(48322, '127.0.0.1', resolve)
})

const env = {
  ...process.env,
  ELECTRON_RUN_AS_NODE: undefined,
  STIMMA_SANDBOX: 'windows-update-e2e',
  STIMMA_DATA_DIR: dataDir,
  STIMMA_CACHE_DIR: cacheDir,
}
let app = spawn(installedExe, ['--remote-debugging-port=48323'], {
  env,
  detached: false,
  stdio: 'ignore',
})

async function waitFor(fn, label, timeout = 120_000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    try {
      const result = await fn()
      if (result) return result
    } catch { /* not ready yet */ }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`timed out: ${label}`)
}

function installedVersion() {
  const result = spawnSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    '(Get-Item -LiteralPath $env:STIMMA_TEST_EXE).VersionInfo.FileVersion',
  ], { env: { ...process.env, STIMMA_TEST_EXE: installedExe }, encoding: 'utf8' })
  return result.status === 0 ? result.stdout.trim() : null
}

function updaterInstallerRunning() {
  const result = spawnSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    '$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "$env:LOCALAPPDATA\\stimma-shell-updater\\pending\\*Setup*.exe" }; if($p){"yes"}',
  ], { encoding: 'utf8' })
  return result.status === 0 && result.stdout.trim() === 'yes'
}

function stopInstalledProcesses() {
  const result = spawnSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    '$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "$env:STIMMA_TEST_ROOT*" }; if($p){Stop-Process -Id @($p.ProcessId) -Force -ErrorAction SilentlyContinue}',
  ], {
    env: { ...process.env, STIMMA_TEST_ROOT: path.dirname(installedExe) },
    stdio: 'inherit',
  })
  assert.equal(result.status, 0, 'failed to stop installed test processes')
}

let browser
async function connectToStimma() {
  const connected = await waitFor(
    () => chromium.connectOverCDP('http://127.0.0.1:48323'),
    'DevTools endpoint',
    180_000,
  )
  const page = await waitFor(() => {
    const pages = connected.contexts().flatMap((context) => context.pages())
    return pages.find((candidate) => candidate.url().startsWith('app://stimma'))
  }, 'Stimma renderer')
  await page.waitForFunction(() => window.stimmaDesktop?.kind === 'electron')
  return { connected, page }
}

try {
  let connected = await connectToStimma()
  browser = connected.connected
  const page = connected.page

  assert.equal(await page.evaluate(() => localStorage.getItem('stimma_global_theme')), 'dark')
  const marker = JSON.parse(readFileSync(path.join(dataDir, 'webkit-storage-imported.json'), 'utf8'))
  assert.equal(marker.imported, true)
  console.log('ok - installed Electron imported Tauri WebView2 localStorage')

  const found = await page.evaluate(async () => {
    const update = await window.stimmaDesktop.checkForUpdate()
    if (!update) return null
    const version = update.version
    await update.download()
    await update.install()
    await update.close()
    return version
  })
  assert.equal(found, expectedVersion)
  console.log(`ok - installed Electron downloaded ${found}`)

  await page.evaluate(() => window.stimmaDesktop.relaunch()).catch(() => {})
  await browser.close().catch(() => {})
  browser = undefined
  await waitFor(() => installedVersion() === expectedVersion, 'installed version replacement', 180_000)
  // The main executable is replaced before the large portable backend has
  // finished extracting. Never launch from that half-written directory.
  await waitFor(() => !updaterInstallerRunning(), 'NSIS extraction completion', 180_000)
  stopInstalledProcesses()
  app = spawn(installedExe, ['--remote-debugging-port=48323'], {
    env,
    detached: false,
    stdio: 'ignore',
  })
  connected = await connectToStimma()
  browser = connected.connected
  assert.equal(
    await connected.page.evaluate(() => window.stimmaDesktop.getAppVersion()),
    expectedVersion,
  )
  console.log('ok - NSIS replaced and relaunched the installed Electron app in place')
} finally {
  await browser?.close().catch(() => {})
  app.kill()
  stopInstalledProcesses()
  await new Promise((resolve) => server.close(resolve))
}
