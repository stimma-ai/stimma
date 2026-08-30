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
 * publishing latest-mac.yml / latest.yml / latest-linux.yml next to the
 * Tauri-era latest.json. The endpoint is baked in at build time via
 * package.json extraMetadata (stimmaUpdateUrl), mirroring how the Tauri
 * conf embedded its endpoint; dev builds have none and the updater is off.
 */

import { app } from 'electron'
import { readPackagedMetadata } from './identity'
import { log } from './log'

interface UpdaterState {
  available: { version: string; body?: string; date?: string } | null
  downloaded: boolean
}

const state: UpdaterState = { available: null, downloaded: false }

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
    autoUpdater.on('update-downloaded', () => {
      state.downloaded = true
    })
  }
  return autoUpdaterModule.autoUpdater
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
    state.available = null
    return null
  }
  state.available = {
    version: info.version,
    body: typeof info.releaseNotes === 'string' ? info.releaseNotes : undefined,
    date: info.releaseDate,
  }
  state.downloaded = false
  return state.available
}

export async function updaterDownload(): Promise<void> {
  if (!state.available) throw new Error('No update available')
  await getAutoUpdater().downloadUpdate()
  // Belt to the update-downloaded event's suspenders: the promise resolving
  // means the package is staged.
  state.downloaded = true
}

export async function updaterInstall(): Promise<void> {
  // macOS/Linux: the downloaded package is applied at quit (or via
  // quitAndInstall from relaunch). Nothing to do beyond validating state.
  if (!state.downloaded) throw new Error('Update not downloaded')
}

export async function updaterDownloadAndInstall(): Promise<void> {
  if (!state.available) throw new Error('No update available')
  if (!state.downloaded) await getAutoUpdater().downloadUpdate()
  getAutoUpdater().quitAndInstall(false, true)
}

export function updaterClose(): void {
  // The Tauri resource-lifecycle close has no electron-updater equivalent.
  // Deliberately do NOT clear `downloaded`: the renderer closes its handle
  // after staging, and a staged package must still apply on relaunch.
  state.available = null
}

/**
 * Updater-aware relaunch: when an update is staged, relaunching must run the
 * installer (quitAndInstall) instead of a plain relaunch, or macOS would
 * relaunch the old bundle out from under Squirrel.
 */
export function relaunchApp(): void {
  if (state.downloaded) {
    getAutoUpdater().quitAndInstall(false, true)
    return
  }
  app.relaunch()
  app.exit(0)
}
