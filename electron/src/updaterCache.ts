/**
 * Guards against electron-updater's staged-update cache going stale.
 *
 * electron-updater keeps a downloaded package in
 * `<cache>/<updaterCacheDirName>/pending/` alongside an `update-info.json`
 * describing it, and installs it on quit when `autoInstallOnAppQuit` is set.
 *
 * Two upstream behaviours combine badly for AppImage:
 *
 *  - `DownloadedUpdateHelper.getValidCachedUpdateFile()` cleans the pending
 *    directory on every validation failure *except* "Cached update file
 *    doesn't exist", where it returns null and leaves `update-info.json`
 *    behind. A successful install moves the package out of `pending/`, so the
 *    descriptor outlives the package it describes — permanently.
 *  - `AppImageUpdater.doInstall()` unlinks the *running* AppImage before it
 *    moves the staged one into place. If that move has nothing to move, the
 *    unlink has already happened and the installed app is gone: the launcher
 *    then points at a path that no longer exists and nothing starts.
 *
 * So we prune a descriptor whose package has vanished, and refuse the
 * quit-time install when the staged package is missing. Neither changes the
 * happy path: with a package actually staged, install-on-quit behaves exactly
 * as before.
 */

import { existsSync, readFileSync, rmSync } from 'node:fs'
import { homedir } from 'node:os'
import * as path from 'node:path'

/**
 * Mirrors electron-updater's `getAppCacheDir()` (out/AppAdapter.js). The
 * pending cache lives outside userData, so it has to be located the same way
 * electron-updater does or we would prune the wrong directory.
 */
export function appCacheRoot(
  platform: NodeJS.Platform = process.platform,
  env: NodeJS.ProcessEnv = process.env,
  home: string = homedir(),
): string {
  if (platform === 'win32') {
    return env.LOCALAPPDATA || path.join(home, 'AppData', 'Local')
  }
  if (platform === 'darwin') {
    return path.join(home, 'Library', 'Caches')
  }
  return env.XDG_CACHE_HOME || path.join(home, '.cache')
}

export function pendingUpdateDir(cacheDirName: string, root: string = appCacheRoot()): string {
  return path.join(root, cacheDirName, 'pending')
}

/**
 * electron-builder stamps `updaterCacheDirName` into resources/app-update.yml.
 * Read just that key rather than pulling in a YAML parser for one scalar.
 */
export function readUpdaterCacheDirName(appUpdateYmlPath: string): string | null {
  let text: string
  try {
    text = readFileSync(appUpdateYmlPath, 'utf8')
  } catch {
    return null
  }
  const match = /^updaterCacheDirName:[ \t]*(.+?)[ \t]*$/m.exec(text)
  if (!match) return null
  return match[1].replace(/^['"]|['"]$/g, '') || null
}

export interface StagedUpdate {
  /** Package file name recorded in update-info.json. */
  fileName: string
  /** Absolute path the package should occupy. */
  path: string
  /** Whether that package is actually still on disk. */
  present: boolean
}

/**
 * Describes what `pending/update-info.json` currently points at, or null when
 * there is no descriptor (nothing staged) or it is unreadable — electron-updater
 * already cleans up the unreadable case itself.
 */
export function readStagedUpdate(pendingDir: string): StagedUpdate | null {
  const infoPath = path.join(pendingDir, 'update-info.json')
  let raw: string
  try {
    raw = readFileSync(infoPath, 'utf8')
  } catch {
    return null
  }
  let fileName: unknown
  try {
    fileName = (JSON.parse(raw) as { fileName?: unknown }).fileName
  } catch {
    return null
  }
  if (typeof fileName !== 'string' || fileName.length === 0) return null
  // Descriptors are written by electron-updater, but this path feeds an
  // unlink-then-move install, so refuse anything that escapes pending/.
  const target = path.join(pendingDir, fileName)
  if (path.dirname(target) !== path.normalize(pendingDir)) return null
  return { fileName, path: target, present: existsSync(target) }
}

/** True when a package is staged and still on disk, i.e. safe to install. */
export function hasStagedPackage(pendingDir: string): boolean {
  return readStagedUpdate(pendingDir)?.present === true
}

/**
 * Drops an `update-info.json` whose package is gone, so the next check
 * re-downloads instead of resurrecting a descriptor electron-updater will
 * never clear on its own. Returns the pruned file name, or null if there was
 * nothing stale to prune.
 */
export function pruneStagedUpdate(pendingDir: string): string | null {
  const staged = readStagedUpdate(pendingDir)
  if (staged == null || staged.present) return null
  try {
    rmSync(path.join(pendingDir, 'update-info.json'), { force: true })
  } catch {
    return null
  }
  return staged.fileName
}
