/**
 * One-time import of Tauri-era localStorage into Electron Chromium.
 *
 * WKWebView leaves DOM storage on disk after the Tauri→Electron update:
 *   custom store:  ~/Library/WebKit/<bundleId>/WebsiteDataStore/<uuid>/
 *                    Origins/<hash>/<hash>/LocalStorage/localstorage.sqlite3
 *     (<uuid> = 16 raw bytes at <dataDir>/browser/data-store-id)
 *   default store: ~/Library/WebKit/<bundleId>/WebsiteData/Default/
 *                    <hash>/<hash>/LocalStorage/localstorage.sqlite3
 *     (production builds never set a data-store-id)
 *
 * Windows/WebView2: <dataDir>/browser/EBWebView/Default/
 *                     Local Storage/leveldb
 *   Older Windows builds used <bundleRoot>/EBWebView instead of the sandbox.
 *
 * The macOS origin-hash directories are salted and not derivable, so candidates are
 * enumerated and identified by content (presence of stimma keys). The dump is
 * read via the stimma-native helper before any window exists, then injected
 * into localStorage by the preload — before any page script runs — writing
 * only keys that don't already exist. The WKWebView source is never touched,
 * so rolling back to a Tauri build keeps its state.
 *
 * A successful-import marker at <dataDir>/webkit-storage-imported.json makes
 * the migration one-shot per sandbox. Negative results remain retryable: a
 * helper/build failure or source that appears after the first Electron start
 * must not permanently strand the Tauri state. Dev sandboxes are included:
 * Tauri and Electron share the same data directory there.
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { helperRequest } from './helper'
import type { AppIdentity } from './identity'
import { log } from './log'

let pendingDump: Record<string, string> | null = null
let markerPath: string | null = null

export function getLegacyStorageDump(): Record<string, string> | null {
  return pendingDump
}

/** Called (idempotently) once a window's preload has written the keys. */
export function markLegacyStorageImported(keysWritten: number): void {
  if (!markerPath || !pendingDump) return
  writeMarker(markerPath, {
    imported: true,
    keys: Object.keys(pendingDump).length,
    written: keysWritten,
    at: new Date().toISOString(),
  })
  log.info('legacy-storage', `Imported ${keysWritten} keys from WKWebView localStorage`)
  pendingDump = null
}

function writeMarker(target: string, value: unknown): void {
  try {
    fs.writeFileSync(target, JSON.stringify(value, null, 2))
  } catch (e) {
    log.warn('legacy-storage', `Failed to write marker: ${e}`)
  }
}

function uuidFromDataStoreId(dataDir: string): string | null {
  try {
    const bytes = fs.readFileSync(path.join(dataDir, 'browser', 'data-store-id'))
    if (bytes.length !== 16) return null
    const hex = Buffer.from(bytes).toString('hex')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  } catch {
    return null
  }
}

function originCandidates(originsRoot: string): string[] {
  const out: string[] = []
  let level1: string[] = []
  try {
    level1 = fs.readdirSync(originsRoot)
  } catch {
    return out
  }
  for (const outer of level1) {
    const outerPath = path.join(originsRoot, outer)
    let level2: string[] = []
    try {
      level2 = fs.readdirSync(outerPath)
    } catch {
      continue
    }
    for (const inner of level2) {
      const candidate = path.join(outerPath, inner, 'LocalStorage', 'localstorage.sqlite3')
      if (fs.existsSync(candidate)) out.push(candidate)
    }
  }
  return out
}

type LegacyCandidate = {
  path: string
  helperMethod: 'read_webkit_local_storage' | 'read_chromium_local_storage'
}

function discoverCandidates(identity: AppIdentity): LegacyCandidate[] {
  // Test/dev override: point straight at a database file.
  const override = process.env.STIMMA_LEGACY_STORAGE_DB
  if (override) {
    return fs.existsSync(override)
      ? [{
        path: override,
        helperMethod: fs.statSync(override).isDirectory()
          ? 'read_chromium_local_storage'
          : 'read_webkit_local_storage',
      }]
      : []
  }

  // WebKitGTK keeps the Tauri origin's localStorage directly inside the
  // configured webview data directory.  Unlike WKWebView on macOS there is
  // no salted origin tree to discover.
  if (process.platform === 'linux') {
    const localStorageRoot = path.join(identity.dataDir, 'browser', 'localstorage')
    try {
      return fs.readdirSync(localStorageRoot)
        .filter((name) => name.endsWith('.localstorage'))
        .map((name) => ({
          path: path.join(localStorageRoot, name),
          helperMethod: 'read_webkit_local_storage' as const,
        }))
    } catch {
      return []
    }
  }

  if (process.platform === 'win32') {
    const suffix = path.join('EBWebView', 'Default', 'Local Storage', 'leveldb')
    const candidates = [
      path.join(identity.dataDir, 'browser', suffix),
      // Pre-sandbox Windows Tauri builds stored WebView2 beside `default/`.
      path.join(path.dirname(identity.dataDir), suffix),
    ]
    return [...new Set(candidates)]
      .filter((candidate) => fs.existsSync(candidate))
      .map((candidate) => ({
        path: candidate,
        helperMethod: 'read_chromium_local_storage' as const,
      }))
  }

  if (process.platform !== 'darwin') return []

  const webkitRoot = path.join(os.homedir(), 'Library', 'WebKit', identity.bundleId)
  const candidates: string[] = []

  const uuid = uuidFromDataStoreId(identity.dataDir)
  if (uuid) {
    const storeRoot = path.join(webkitRoot, 'WebsiteDataStore')
    // Directory case can differ from our lowercase rendering; match loosely.
    try {
      for (const entry of fs.readdirSync(storeRoot)) {
        if (entry.toLowerCase() === uuid.toLowerCase()) {
          candidates.push(...originCandidates(path.join(storeRoot, entry, 'Origins')))
        }
      }
    } catch {
      // No custom stores on disk.
    }
  }

  // Default (unkeyed) data store — production builds, or any profile that
  // predates the custom-store code.
  candidates.push(...originCandidates(path.join(webkitRoot, 'WebsiteData', 'Default')))

  return candidates.map((candidate) => ({
    path: candidate,
    helperMethod: 'read_webkit_local_storage' as const,
  }))
}

function looksLikeStimmaDump(items: Record<string, string>): boolean {
  if ('stimma_bundle_id' in items || 'profileId' in items) return true
  return Object.keys(items).some((key) => key.startsWith('stimma'))
}

/**
 * Resolve the WKWebView localStorage dump for this identity, if any. Runs
 * once per sandbox (marker-gated) before the first window is created.
 */
export async function prepareLegacyStorageImport(identity: AppIdentity): Promise<void> {
  markerPath = path.join(identity.dataDir, 'webkit-storage-imported.json')
  try {
    const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8')) as { imported?: boolean }
    if (marker.imported === true) return
  } catch {
    // Missing/corrupt/negative markers are safe to retry.
  }

  const candidates = discoverCandidates(identity)
  if (candidates.length === 0) {
    // Record the diagnostic, but a later launch may retry if a Tauri source
    // appears (for example after rollback and another shell upgrade).
    writeMarker(markerPath, { imported: false, reason: 'no-source', at: new Date().toISOString() })
    return
  }

  let readFailed = false
  for (const candidate of candidates) {
    try {
      const result = (await helperRequest(candidate.helperMethod, {
        db_path: candidate.path,
      })) as { items?: Record<string, string> }
      const items = result?.items ?? {}
      if (looksLikeStimmaDump(items)) {
        log.info(
          'legacy-storage',
          `Found Tauri localStorage (${Object.keys(items).length} keys): ${candidate.path}`,
        )
        pendingDump = items
        return
      }
    } catch (e) {
      readFailed = true
      log.warn('legacy-storage', `Failed reading ${candidate.path}: ${e}`)
    }
  }

  // Do not turn a transient helper/database error into permanent data loss.
  if (readFailed) return

  writeMarker(markerPath, { imported: false, reason: 'no-stimma-origin', at: new Date().toISOString() })
}
