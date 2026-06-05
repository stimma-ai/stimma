/**
 * One-time localStorage cleanup run on startup.
 *
 * Purges three classes of entries:
 *   - Every mask/paint entry (masks and paint layers are now in IndexedDB via
 *     blobStorage — clean break, no migration).
 *   - Every tool-descriptor cache entry (cache was dropped — stale schemas
 *     aren't worth 100KB–700KB apiece).
 *   - Legacy `stimma_tool_...` keys that predate the scope-token format in
 *     storageKeys.ts and are no longer read by any code path.
 *
 * Runs once per app load from App.vue startup, after setAppModifier so the
 * basePrefix matches the current env.
 */

import { getAppModifier } from '../appConfig'

function basePrefix(): string {
  const modifier = getAppModifier()
  return modifier ? `stimma_${modifier}` : 'stimma'
}

function shouldPurge(key: string, prefix: string): boolean {
  if (!key.startsWith(prefix + '_')) return false  // not ours — leave alone

  // Drop all mask / paint entries (moved to IndexedDB).
  if (key.includes('_mask')) return true
  if (/_paint(_\d+)?$/.test(key)) return true

  // Drop all tool-descriptor cache entries (feature removed).
  if (key.endsWith('_tool_descriptor')) return true

  // Drop legacy `stimma_tool_*` keys (pre-scope-token format). Current keys
  // always have a scope token (dbGuid / profileId / "global") between the
  // prefix and any functional segment, so `stimma_{prefix}_tool_...` with
  // "tool" directly after the prefix is always legacy.
  const rest = key.slice(prefix.length + 1)
  if (rest.startsWith('tool_')) return true

  return false
}

let cleanupDone = false

export function runStartupCleanup(): void {
  if (cleanupDone) return
  cleanupDone = true

  const prefix = basePrefix()
  const toRemove: string[] = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      if (shouldPurge(key, prefix)) toRemove.push(key)
    }
    for (const key of toRemove) {
      try { localStorage.removeItem(key) } catch { /* ignore */ }
    }
    if (toRemove.length > 0) {
      console.log(`[storageCleanup] purged ${toRemove.length} localStorage keys`)
    }
  } catch (e) {
    console.warn('[storageCleanup] failed:', e)
  }
}
