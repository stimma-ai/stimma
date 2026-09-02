/**
 * electron-updater integration.
 *
 * The renderer keeps the exact updater flow it had under Tauri (check →
 * handle with download/install/downloadAndInstall/close). This module adapts
 * that contract onto electron-updater:
 *  - macOS/Linux: download() stages the update (Squirrel.Mac / AppImage
 *    swap applies at quit); install() is a no-op beyond marking staged.
 *  - Windows: download() fetches the NSIS package; the deferred-apply UX is
 *    the renderer's (it only downloads at "restart to update" time).
 *  - relaunch() becomes quitAndInstall() whenever an update is staged, so
 *    the renderer's existing relaunch path applies updates correctly.
 *
 * Feed: generic provider at
 *   <STIMMA_UPDATE_BASE_URL>/stimma/<channel>/<platform>/
 * publishing the platform's `latest` Electron manifest next to the Tauri-era
 * latest.json. (Each release channel has its own feed directory.) The endpoint
 * is baked in at build time via
 * package.json extraMetadata (stimmaUpdateUrl), mirroring how the Tauri
 * conf embedded its endpoint; dev builds have none and the updater is off.
 */

import { app } from 'electron'
import * as path from 'node:path'
import { shutdownBackend } from './backend'
import { shutdownHelper } from './helper'
import { readPackagedMetadata } from './identity'
import { log } from './log'
import { beginUpdateInstall } from './updaterLifecycle'
import { UpdaterState } from './updaterState'
import {
  hasStagedPackage,
  pendingUpdateDir,
  pruneStagedUpdate,
  readUpdaterCacheDirName,
} from './updaterCache'
import { markQuitting } from './windows'

const state = new UpdaterState()

/**
 * Where electron-updater stages the downloaded package, or null when we can't
 * work it out (unpackaged, or app-update.yml missing its cache dir name).
 */
function stagingDir(): string | null {
  if (!app.isPackaged) return null
  const cacheDirName = readUpdaterCacheDirName(path.join(process.resourcesPath, 'app-update.yml'))
  if (!cacheDirName) return null
  return pendingUpdateDir(cacheDirName)
}

let autoUpdaterModule: typeof import('electron-updater') | null = null

function feedUrl(): string | null {
  return readPackagedMetadata(app.getAppPath()).stimmaUpdateUrl || null
}

function getAutoUpdater() {
  if (!autoUpdaterModule) {
    // Lazy: dev builds without a feed never load electron-updater.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    autoUpdaterModule = require('electron-updater') as typeof import('electron-updater')
    const { autoUpdater } = autoUpdaterModule
    autoUpdater.autoDownload = false
    autoUpdater.autoInstallOnAppQuit = true
    // Each Stimma release channel already has an isolated feed directory.
    // Pin the manifest name to latest(.yml/-mac.yml) so prerelease semver
    // labels do not make electron-updater unexpectedly request canary.yml or
    // beta.yml. Setting channel toggles allowDowngrade in electron-updater;
    // turn it back off so a stale feed can never roll an install backward.
    autoUpdater.channel = 'latest'
    autoUpdater.allowDowngrade = false
    autoUpdater.logger = {
      info: (m: unknown) => log.info('updater', String(m)),
      warn: (m: unknown) => log.warn('updater', String(m)),
      error: (m: unknown) => log.error('updater', String(m)),
      debug: (m: unknown) => log.debug('updater', String(m)),
    }
    const url = feedUrl()
    if (url) {
      autoUpdater.setFeedURL({ provider: 'generic', url })
    }
    autoUpdater.on('update-downloaded', (info) => {
      const version = info.version || state.available?.version
      if (version) state.markDownloaded(version)
    })
    installStagedUpdateGuard(autoUpdater)
  }
  return autoUpdaterModule.autoUpdater
}

/**
 * Keeps install-on-quit enabled but never lets it run against a package that
 * isn't there. See updaterCache.ts: AppImageUpdater.doInstall() deletes the
 * running AppImage *before* moving the staged one in, so installing with the
 * staged package already gone uninstalls the app instead of updating it.
 */
function installStagedUpdateGuard(autoUpdater: {
  autoInstallOnAppQuit: boolean
}): void {
  const pendingDir = stagingDir()
  if (!pendingDir) return

  // A successful install moves the package out of pending/ but leaves
  // update-info.json behind, and electron-updater never clears it. Drop it now
  // so the next check re-downloads rather than pointing at a missing file.
  const pruned = pruneStagedUpdate(pendingDir)
  if (pruned) {
    log.warn('updater', `Discarded stale staged update with no package on disk: ${pruned}`)
  }

  // 'will-quit' always precedes the 'quit' listener electron-updater installs,
  // regardless of which registered first, so this decides whether its
  // quit-time install is allowed to proceed.
  app.on('will-quit', () => {
    if (autoUpdater.autoInstallOnAppQuit && !hasStagedPackage(pendingDir)) {
      log.warn('updater', 'Skipping install on quit: staged update package is missing.')
      autoUpdater.autoInstallOnAppQuit = false
    }
  })
}

export function updatesSupported(): boolean {
  return app.isPackaged && !!feedUrl()
}

export async function updaterCheck(): Promise<{
  version: string
  body?: string
  date?: string
} | null> {
  if (!updatesSupported()) return null
  const autoUpdater = getAutoUpdater()
  const result = await autoUpdater.checkForUpdates()
  const info = result?.updateInfo
  if (!info || !result?.isUpdateAvailable) {
    state.recordCheck(null)
    return null
  }
  state.recordCheck({
    version: info.version,
    body: typeof info.releaseNotes === 'string' ? info.releaseNotes : undefined,
    date: info.releaseDate,
  })
  return state.available
}

export async function updaterDownload(): Promise<void> {
  if (!state.available) throw new Error('No update available')
  const version = state.available.version
  await getAutoUpdater().downloadUpdate()
  // Belt to the update-downloaded event's suspenders: the promise resolving
  // means the package is staged.
  state.markDownloaded(version)
}

export async function updaterInstall(): Promise<void> {
  // macOS/Linux: the downloaded package is applied at quit (or via
  // quitAndInstall from relaunch). Nothing to do beyond validating state.
  if (!state.hasDownloadedAvailableUpdate()) throw new Error('Update not downloaded')
}

export async function updaterDownloadAndInstall(): Promise<void> {
  if (!state.available) throw new Error('No update available')
  if (!state.hasDownloadedAvailableUpdate()) {
    const version = state.available.version
    await getAutoUpdater().downloadUpdate()
    state.markDownloaded(version)
  }
  // Keep the bridge call awaitable. The renderer follows this with relaunch(),
  // which performs the one authoritative quitAndInstall after the backend and
  // helper have released the installation tree. Calling it here as well races
  // two installers and returns before Electron has actually quit.
}

export function updaterClose(): void {
  // The Tauri resource-lifecycle close has no electron-updater equivalent.
  // Deliberately do NOT clear `downloaded`: the renderer closes its handle
  // after staging, and a staged package must still apply on relaunch.
  state.closeAvailableHandle()
}

/**
 * Updater-aware relaunch: when an update is staged, relaunching must run the
 * installer (quitAndInstall) instead of a plain relaunch, or macOS would
 * relaunch the old bundle out from under Squirrel.
 */
export function relaunchApp(): void {
  if (state.hasDownloadedUpdate()) {
    // NSIS refuses to proceed while packaged Python/native binaries are alive.
    // Stop them before launching the installer, while the watchdog still owns
    // the complete backend process tree. electron-updater closes windows before
    // emitting before-quit, so mark the app as quitting first; otherwise the
    // last-window handler hides the window and cancels the macOS installer quit.
    beginUpdateInstall({
      markQuitting,
      shutdownHelper,
      shutdownBackend,
      quitAndInstall: () => getAutoUpdater().quitAndInstall(false, true),
    })
    return
  }
  app.relaunch()
  app.exit(0)
}
