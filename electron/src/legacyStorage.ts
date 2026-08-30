/**
 * One-time import of WKWebView (Tauri-era) localStorage into Chromium.
 *
 * WKWebView leaves DOM storage on disk after the Tauri→Electron update:
 *   custom store:  ~/Library/WebKit/<bundleId>/WebsiteDataStore/<uuid>/
 *                    Origins/<hash>/<hash>/LocalStorage/localstorage.sqlite3
 *     (<uuid> = 16 raw bytes at <dataDir>/browser/data-store-id)
 *   default store: ~/Library/WebKit/<bundleId>/WebsiteData/Default/
 *                    <hash>/<hash>/LocalStorage/localstorage.sqlite3
 *     (production builds never set a data-store-id)
 *
 * The origin-hash directories are salted and not derivable, so candidates are
 * enumerated and identified by content (presence of stimma keys). The dump is
 * read via the stimma-native helper before any window exists, then injected
 * into localStorage by the preload — before any page script runs — writing
 * only keys that don't already exist. The WKWebView source is never touched,
 * so rolling back to a Tauri build keeps its state.
 *
 * A marker at <dataDir>/webkit-storage-imported.json makes the whole thing
 * one-shot per sandbox.
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

function discoverCandidates(identity: AppIdentity): string[] {
  // Test/dev override: point straight at a database file.
  const override = process.env.STIMMA_LEGACY_STORAGE_DB
  if (override) return fs.existsSync(override) ? [override] : []

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

  return candidates
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
  // Dev shells run against the Vite origin and have no WKWebView history to
  // inherit; the env override still allows exercising the path in tests.
  if (identity.dev && !process.env.STIMMA_LEGACY_STORAGE_DB) return

  markerPath = path.join(identity.dataDir, 'webkit-storage-imported.json')
  if (fs.existsSync(markerPath)) return

  const candidates = discoverCandidates(identity)
  if (candidates.length === 0) {
    // Fresh install (or non-mac): nothing to import, never look again.
    writeMarker(markerPath, { imported: false, reason: 'no-source', at: new Date().toISOString() })
    return
  }

  for (const candidate of candidates) {
    try {
      const result = (await helperRequest('read_webkit_local_storage', {
        db_path: candidate,
      })) as { items?: Record<string, string> }
      const items = result?.items ?? {}
      if (looksLikeStimmaDump(items)) {
        log.info(
          'legacy-storage',
          `Found WKWebView localStorage (${Object.keys(items).length} keys): ${candidate}`,
        )
        pendingDump = items
        return
      }
    } catch (e) {
      log.warn('legacy-storage', `Failed reading ${candidate}: ${e}`)
    }
  }

  writeMarker(markerPath, { imported: false, reason: 'no-stimma-origin', at: new Date().toISOString() })
}
