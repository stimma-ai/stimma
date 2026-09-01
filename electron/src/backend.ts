/**
 * Backend supervision.
 *
 * Packaged mode: spawn stimma-watchdog with the exact contract the Tauri
 * shell used — same args, same env, same STIMMA_BACKEND_PORT= stdout/stderr
 * parse. Dev mode: the developer runs the backend; the port comes from env.
 */

import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import readline from 'node:readline'
import type { AppIdentity } from './identity'
import { log } from './log'
import { setLocalBackendPort } from './devices'

let backendPort: number | null = null
let watchdogPid: number | null = null

/**
 * Record the backend port and hand it to the device manager, which decides
 * whether the proxy should point here or at a remote device. Every
 * assignment goes through this one place so the two cannot drift.
 */
function setBackendPort(port: number): void {
  backendPort = port
  setLocalBackendPort(port)
}

export function getBackendPortSync(): number | null {
  return backendPort
}

/** Resolve the backend port, waiting up to ~30s (mirrors the Tauri command). */
export async function waitForBackendPort(): Promise<number> {
  for (let i = 0; i < 300; i++) {
    if (backendPort !== null) return backendPort
    if (i % 20 === 0) log.info('backend', `Waiting for port... attempt ${i}/300`)
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Backend port not available after timeout')
}

export function parseBackendPort(line: string): number | null {
  const idx = line.indexOf('STIMMA_BACKEND_PORT=')
  if (idx === -1) return null
  const after = line.slice(idx + 'STIMMA_BACKEND_PORT='.length)
  const match = after.match(/^\d+/)
  if (!match) return null
  const port = Number.parseInt(match[0], 10)
  return Number.isInteger(port) && port > 0 && port < 65536 ? port : null
}

/**
 * Locate the watchdog binary next to the packaged resources. Resources live
 * outside ASAR under process.resourcesPath; dev never calls this.
 */
function watchdogPath(): string {
  const base = path.join(process.resourcesPath, 'stimma-watchdog')
  if (fs.existsSync(base)) return base
  return base + '.exe'
}

export function startBackend(identity: AppIdentity, appVersion: string): void {
  if (identity.dev) {
    setBackendPort(identity.devBackendPort)
    log.info('stimma', `Dev mode: using external backend on port ${backendPort}`)
    return
  }

  fs.mkdirSync(identity.dataDir, { recursive: true })
  fs.mkdirSync(identity.cacheDir, { recursive: true })

  const watchdog = watchdogPath()
  log.info('stimma', `Bundle ID: ${identity.bundleId}`)
  log.info('stimma', `Data dir: ${identity.dataDir}`)
  log.info('stimma', `Cache dir: ${identity.cacheDir}`)
  log.info('stimma', `Spawning watchdog from: ${watchdog}`)

  const child = spawn(
    watchdog,
    [
      '--parent-pid',
      String(process.pid),
      'stimma-backend',
      '--port',
      '0',
      // --bundle-id must be forwarded: without it the backend falls back to
      // the debug bundle id and reports branch "dev" even in official builds.
      '--bundle-id',
      identity.bundleId,
    ],
    {
      env: {
        ...process.env,
        STIMMA_DATA_DIR: identity.dataDir,
        STIMMA_CACHE_DIR: identity.cacheDir,
        STIMMA_DISTRIBUTION: identity.distribution,
        STIMMA_APP_VERSION: appVersion,
        // Prevent the bundled Python from writing .pyc files into the
        // (code-signed) app bundle at runtime, which invalidates the macOS
        // signature seal and triggers "app is damaged".
        PYTHONDONTWRITEBYTECODE: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )

  log.info('stimma', `Watchdog spawned with pid: ${child.pid}`)
  watchdogPid = child.pid ?? null

  const attach = (stream: NodeJS.ReadableStream, level: 'info' | 'warn') => {
    const rl = readline.createInterface({ input: stream })
    rl.on('line', (line) => {
      const port = parseBackendPort(line)
      if (port !== null) {
        log.info('backend', `Detected port: ${port}`)
        setBackendPort(port)
      }
      log[level]('backend', line)
    })
  }
  attach(child.stdout!, 'info')
  attach(child.stderr!, 'warn')

  child.on('exit', (code, signal) => {
    if (watchdogPid === child.pid) watchdogPid = null
    log.error('stimma', `Watchdog exited (code=${code}, signal=${signal})`)
  })
  child.unref()
}

/**
 * Stop the packaged backend before Windows replaces the installation tree.
 *
 * Parent-death monitoring is normally sufficient, but on Windows the cmd.exe
 * launcher can disappear before the watchdog observes Electron's exit. That
 * orphans Python inside resources/ and makes NSIS stop at "cannot be closed".
 * Killing the watchdog tree while it is still intact includes cmd.exe, Python,
 * and multiprocessing children, and spawnSync keeps the installer behind it.
 */
export function shutdownBackend(): void {
  backendPort = null
  if (process.platform !== 'win32' || watchdogPid === null) return

  const pid = watchdogPid
  watchdogPid = null
  log.info('backend', `Stopping watchdog process tree ${pid}`)
  const result = spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], {
    windowsHide: true,
    encoding: 'utf8',
  })
  if (result.status !== 0) {
    log.warn(
      'backend',
      `taskkill for watchdog ${pid} exited ${result.status}: ${result.stderr?.trim() || result.stdout?.trim() || 'unknown error'}`,
    )
  }
}
