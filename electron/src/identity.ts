/**
 * Channel + sandbox identity, resolved before app.ready.
 *
 * Mirrors src-tauri's get_app_dirs(): explicit STIMMA_DATA_DIR/STIMMA_CACHE_DIR
 * override; otherwise the bundle id names the folder and the sandbox nests
 * inside it. Everything identity-derived (userData, single-instance scope,
 * backend dirs, logs) flows from this one module.
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

/**
 * Build-stamped metadata (electron-builder extraMetadata) read from the
 * packaged package.json at RUNTIME. Never `require('../package.json')` in
 * bundled code — esbuild inlines it at build time, before the builder stamps
 * version/bundle id/feed URL.
 */
export interface PackagedMetadata {
  version?: string
  productName?: string
  stimmaBundleId?: string
  stimmaUpdateUrl?: string
}

export function readPackagedMetadata(appPath: string): PackagedMetadata {
  try {
    return JSON.parse(fs.readFileSync(path.join(appPath, 'package.json'), 'utf8'))
  } catch {
    return {}
  }
}

export interface AppIdentity {
  bundleId: string
  sandbox: string
  dev: boolean
  distribution: 'official' | 'dev'
  dataDir: string
  cacheDir: string
  devBackendPort: number
  devFrontendPort: number
}

function defaultDirs(bundleId: string, sandbox: string): { dataDir: string; cacheDir: string } {
  const home = os.homedir()
  if (process.platform === 'darwin') {
    return {
      dataDir: path.join(home, 'Library', 'Application Support', bundleId, sandbox),
      cacheDir: path.join(home, 'Library', 'Caches', bundleId, sandbox),
    }
  }
  if (process.platform === 'win32') {
    const localAppData =
      process.env.LOCALAPPDATA || path.join(process.env.USERPROFILE || home, 'AppData', 'Local')
    const dataDir = path.join(localAppData, bundleId, sandbox)
    return { dataDir, cacheDir: dataDir }
  }
  const xdgData = process.env.XDG_DATA_HOME || path.join(home, '.local', 'share')
  const xdgCache = process.env.XDG_CACHE_HOME || path.join(home, '.cache')
  return {
    dataDir: path.join(xdgData, bundleId, sandbox),
    cacheDir: path.join(xdgCache, bundleId, sandbox),
  }
}

export function resolveIdentity(packagedBundleId: string): AppIdentity {
  const dev = !!process.env.STIMMA_DEV
  const bundleId = process.env.STIMMA_BUNDLE_ID || packagedBundleId
  const sandboxRaw = process.env.STIMMA_SANDBOX
  const sandbox = sandboxRaw && sandboxRaw.trim() ? sandboxRaw : 'default'

  const defaults = defaultDirs(bundleId, sandbox)
  const dataDir = process.env.STIMMA_DATA_DIR || defaults.dataDir
  const cacheDir = process.env.STIMMA_CACHE_DIR || defaults.cacheDir

  return {
    bundleId,
    sandbox,
    dev,
    distribution: process.env.STIMMA_DISTRIBUTION === 'official' ? 'official' : 'dev',
    dataDir,
    cacheDir,
    devBackendPort: Number.parseInt(process.env.STIMMA_BACKEND_PORT || '9191', 10),
    devFrontendPort: Number.parseInt(process.env.STIMMA_FRONTEND_PORT || '9192', 10),
  }
}
