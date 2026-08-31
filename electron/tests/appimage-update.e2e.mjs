// Real AppImage updater regression test. Builds a buggy source release plus
// two fixed releases, serves them from a local generic-provider feed, and
// drives the packaged app through download -> recheck -> relaunch.

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import { createServer } from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { build as esbuild } from 'esbuild'

const electronRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repoRoot = path.dirname(electronRoot)
const frontendRequire = createRequire(path.join(repoRoot, 'frontend', 'package.json'))
const { _electron } = frontendRequire('playwright')
const builder = path.join(electronRoot, 'node_modules', '.bin', 'electron-builder')
const baseConfigPath = path.join(electronRoot, '.generated-builder.json')

const versions = {
  buggy: '9.9.0-update-test.1',
  fixed: '9.9.0-update-test.2',
  next: '9.9.0-update-test.3',
}

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-appimage-update-'))
const feedDir = path.join(work, 'feed')
const installDir = path.join(work, 'install')
const homeDir = path.join(work, 'home')
const dataDir = path.join(work, 'data')
const cacheDir = path.join(work, 'cache')
const marker = `stimma-update-test-${process.pid}`
for (const dir of [feedDir, installDir, homeDir, dataDir, cacheDir]) {
  fs.mkdirSync(dir, { recursive: true })
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || electronRoot,
    env: options.env || process.env,
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`${command} exited with ${result.status}`)
  }
}

function findOne(dir, predicate, description) {
  const matches = fs.readdirSync(dir).filter(predicate)
  assert.equal(matches.length, 1, `expected one ${description} in ${dir}, got ${matches}`)
  return path.join(dir, matches[0])
}

function sha512(file) {
  return crypto.createHash('sha512').update(fs.readFileSync(file)).digest('base64')
}

function count(text, needle) {
  return text.split(needle).length - 1
}

async function waitFor(predicate, message, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const value = await predicate()
    if (value) return value
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`timed out: ${message}`)
}

function markedProcesses() {
  const found = []
  for (const entry of fs.readdirSync('/proc')) {
    if (!/^\d+$/.test(entry)) continue
    try {
      const env = fs.readFileSync(`/proc/${entry}/environ`, 'utf8')
      if (env.includes(`STIMMA_UPDATE_TEST_ID=${marker}\0`)) found.push(Number(entry))
    } catch {
      // Process exited or belongs to another user.
    }
  }
  return found
}

async function stopMarkedProcesses() {
  const self = process.pid
  for (const pid of markedProcesses()) {
    if (pid !== self) {
      try { process.kill(pid, 'SIGTERM') } catch { /* already exited */ }
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 1_000))
  for (const pid of markedProcesses()) {
    if (pid !== self) {
      try { process.kill(pid, 'SIGKILL') } catch { /* already exited */ }
    }
  }
}

const prefix = '/stimma/update-test/linux-x86_64/'
const server = createServer((req, res) => {
  const pathname = decodeURIComponent((req.url || '/').split('?')[0])
  if (!pathname.startsWith(prefix)) {
    res.writeHead(404).end()
    return
  }
  const name = pathname.slice(prefix.length)
  if (!name || name !== path.basename(name)) {
    res.writeHead(400).end()
    return
  }
  const file = path.join(feedDir, name)
  if (!fs.existsSync(file)) {
    res.writeHead(404).end()
    return
  }
  const stat = fs.statSync(file)
  res.writeHead(200, {
    'Content-Length': stat.size,
    'Content-Type': name.endsWith('.yml') ? 'text/yaml' : 'application/octet-stream',
  })
  if (req.method === 'HEAD') res.end()
  else fs.createReadStream(file).pipe(res)
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const feedUrl = `http://127.0.0.1:${server.address().port}${prefix.slice(0, -1)}`

const baseConfig = JSON.parse(fs.readFileSync(baseConfigPath, 'utf8'))
function buildAppImage(version, label) {
  const output = path.join(work, label)
  const config = {
    ...baseConfig,
    appId: 'ai.stimma.stimma.update-test',
    productName: 'Stimma Update Test',
    directories: { ...baseConfig.directories, output },
    extraMetadata: {
      ...baseConfig.extraMetadata,
      version,
      productName: 'Stimma Update Test',
      stimmaBundleId: 'ai.stimma.stimma.update-test',
      desktopName: 'ai.stimma.stimma.update-test.desktop',
      stimmaUpdateUrl: feedUrl,
    },
    publish: { provider: 'generic', url: feedUrl },
  }
  delete config.mac
  const configPath = path.join(work, `${label}.json`)
  fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`)
  run(builder, ['--config', configPath, '--publish', 'never'])
  return {
    appImage: findOne(output, (name) => name.endsWith('.AppImage'), 'AppImage'),
    manifest: findOne(output, (name) => name.endsWith('-linux.yml'), 'Linux manifest'),
  }
}

function publish(release) {
  for (const name of fs.readdirSync(feedDir)) fs.rmSync(path.join(feedDir, name))
  fs.copyFileSync(release.appImage, path.join(feedDir, path.basename(release.appImage)))
  fs.copyFileSync(release.manifest, path.join(feedDir, 'latest-linux.yml'))
}

const mainBundle = path.join(electronRoot, 'dist', 'main.cjs')
const mainMap = `${mainBundle}.map`
let fixedMain
let fixedMap
let activeApp = null

async function buildBuggyMain() {
  const buggyState = `
    export class UpdaterState {
      available = null
      downloadedVersion = null
      recordCheck(available) { this.available = available; this.downloadedVersion = null }
      markDownloaded(version) { this.downloadedVersion = version }
      closeAvailableHandle() { this.available = null }
      hasDownloadedUpdate() { return this.downloadedVersion !== null }
      hasDownloadedAvailableUpdate() {
        return this.available !== null && this.downloadedVersion === this.available.version
      }
    }
  `
  await esbuild({
    bundle: true,
    platform: 'node',
    format: 'cjs',
    sourcemap: true,
    external: ['electron', 'electron-updater'],
    entryPoints: [path.join(electronRoot, 'src', 'main.ts')],
    outfile: mainBundle,
    plugins: [{
      name: 'buggy-updater-state',
      setup(build) {
        build.onResolve({ filter: /updaterState$/ }, () => ({ path: 'buggy', namespace: 'buggy' }))
        build.onLoad({ filter: /.*/, namespace: 'buggy' }, () => ({
          contents: buggyState,
          loader: 'ts',
        }))
      },
    }],
  })
}

function restoreFixedMain() {
  fs.writeFileSync(mainBundle, fixedMain)
  fs.writeFileSync(mainMap, fixedMap)
}

function appEnv(sandbox) {
  const env = { ...process.env }
  for (const key of ['ELECTRON_RUN_AS_NODE', 'APPIMAGE', 'APPDIR', 'OWD']) delete env[key]
  return {
    ...env,
    HOME: homeDir,
    XDG_DATA_HOME: path.join(homeDir, '.local', 'share'),
    XDG_CACHE_HOME: path.join(homeDir, '.cache'),
    XDG_CONFIG_HOME: path.join(homeDir, '.config'),
    STIMMA_DATA_DIR: dataDir,
    STIMMA_CACHE_DIR: cacheDir,
    STIMMA_SANDBOX: sandbox,
    STIMMA_UPDATE_TEST_ID: marker,
    APPIMAGE_SILENT_INSTALL: 'true',
  }
}

async function launch(executable, sandbox) {
  const app = await _electron.launch({ executablePath: executable, args: [], env: appEnv(sandbox) })
  const page = await app.firstWindow()
  await page.waitForURL('app://stimma/**', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => window.stimmaDesktop?.kind === 'electron')
  return { app, page }
}

async function stageRecheckAndRelaunch(running, expectedVersion) {
  const current = await running.page.evaluate(() => window.stimmaDesktop.getAppVersion())
  const staged = await running.page.evaluate(async (expected) => {
    const update = await window.stimmaDesktop.checkForUpdate()
    if (!update) throw new Error(`no update available; expected ${expected}`)
    if (update.version !== expected) throw new Error(`got ${update.version}; expected ${expected}`)
    await update.download()
    await update.install()
    await update.close()
    return update.version
  }, expectedVersion)
  assert.equal(staged, expectedVersion)

  // This is the production trigger: the scheduled checker runs again while
  // the downloaded update is waiting for a restart.
  const rechecked = await running.page.evaluate(async () => {
    const update = await window.stimmaDesktop.checkForUpdate()
    if (!update) return null
    const version = update.version
    await update.close()
    return version
  })
  assert.equal(rechecked, expectedVersion)

  await running.page.evaluate(() => window.stimmaDesktop.relaunch()).catch(() => {})
  // Do not wait on Playwright's Electron connection here. AppImage relaunch can
  // leave the launcher process attached to that connection after the original
  // main process exits. The externally observable replacement, shell startup,
  // and backend handshake below are the actual update success conditions.
  return current
}

try {
  assert.ok(fs.existsSync(baseConfigPath), 'run tools/stimma app build once before this test')
  run('npm', ['run', 'build'])
  fixedMain = fs.readFileSync(mainBundle)
  fixedMap = fs.readFileSync(mainMap)

  console.log('building buggy source AppImage...')
  await buildBuggyMain()
  const buggy = buildAppImage(versions.buggy, 'buggy')

  console.log('building fixed AppImages...')
  restoreFixedMain()
  const fixed = buildAppImage(versions.fixed, 'fixed')
  const next = buildAppImage(versions.next, 'next')

  const installed = path.join(installDir, 'Stimma-Update-Test.AppImage')
  fs.copyFileSync(buggy.appImage, installed)
  fs.chmodSync(installed, 0o755)
  publish(fixed)

  console.log('exercising buggy -> fixed with forced recheck...')
  activeApp = await launch(installed, 'update-test-bridge')
  await stageRecheckAndRelaunch(activeApp, versions.fixed)
  activeApp = null
  await waitFor(() => sha512(installed) === sha512(fixed.appImage), 'fixed AppImage replacement')

  // The old updater cannot be repaired retroactively. Its deterministic bug is
  // that the forced recheck loses the downloaded state and falls back to the
  // updater's auto-install-on-quit path. Whether that path loses its AppImage
  // mount is a timing race, so do not require the old binary to crash here.
  await new Promise((resolve) => setTimeout(resolve, 5_000))
  const bridgeLog = fs.readFileSync(path.join(dataDir, 'Logs', 'Stimma-shell.log'), 'utf8')
  assert.match(bridgeLog, /Auto install update on quit/)
  await stopMarkedProcesses()

  console.log('recovering by launching the installed fixed AppImage...')
  activeApp = await launch(installed, 'update-test-fixed')
  assert.equal(
    await activeApp.page.evaluate(() => window.stimmaDesktop.getAppVersion()),
    versions.fixed,
  )

  publish(next)
  const logPath = path.join(dataDir, 'Logs', 'Stimma-shell.log')
  const startsBefore = count(fs.readFileSync(logPath, 'utf8'), 'Starting Electron shell')
  console.log('exercising fixed -> fixed with forced recheck...')
  await stageRecheckAndRelaunch(activeApp, versions.next)
  activeApp = null
  await waitFor(() => sha512(installed) === sha512(next.appImage), 'next AppImage replacement')
  await waitFor(() => {
    const log = fs.readFileSync(logPath, 'utf8')
    const tail = log.slice(log.lastIndexOf('Starting Electron shell'))
    return count(log, 'Starting Electron shell') > startsBefore && tail.includes('Detected port:')
  }, 'fixed app relaunch and backend handshake', 60_000)
  assert.ok(markedProcesses().length > 0, 'fixed relaunched process should remain alive')

  const finalLog = fs.readFileSync(logPath, 'utf8')
  const finalTail = finalLog.slice(finalLog.lastIndexOf('Starting Electron shell'))
  assert.doesNotMatch(finalTail, /Transport endpoint is not connected|No module named|Failed to spawn backend/)
  console.log('ok - real fixed AppImage update survived a post-download recheck')
  console.log('ok - replacement shell, watchdog, renderer, and Python backend returned')
} finally {
  if (fixedMain && fixedMap) restoreFixedMain()
  if (activeApp) await activeApp.app.close().catch(() => {})
  await stopMarkedProcesses()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(work, { recursive: true, force: true })
}
