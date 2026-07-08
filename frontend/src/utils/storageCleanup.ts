/**
 * One-time localStorage cleanup run on startup.
 *
 * Purges four classes of entries:
 *   - Every mask/paint entry (masks and paint layers are now in IndexedDB via
 *     blobStorage — clean break, no migration).
 *   - Every tool-descriptor cache entry (cache was dropped — stale schemas
 *     aren't worth 100KB–700KB apiece).
 *   - Legacy `stimma_tool_...` keys that predate the scope-token format in
 *     storageKeys.ts and are no longer read by any code path.
 *   - Orphaned tool-instance keys (`...__i_{K}...`): every tool tab is an
 *     instance with per-instance state/overlay keys; a closed tab's keys are
 *     kept for the rest of the session (⌘⇧T restores them) and swept here on
 *     the next boot once no persisted tab references the instance id.
 *     The matching IndexedDB blobs (mask/paint) are swept too.
 *
 * Runs once per app load from App.vue startup, after setAppModifier so the
 * basePrefix matches the current env.
 */

import { getAppModifier } from '../appConfig'
import { listBlobKeys, deleteBlob } from './blobStorage'

const INSTANCE_TOKEN_RE = /__i_(\d+)(?:[^0-9]|$)/

/**
 * Collect the set of live tool-instance ids from every persisted
 * workspace_tabs blob under our prefix. Instance ids are minted from ONE
 * global counter, so ids are unique across profiles and the union is exact.
 * `migrationPending` is true when any blob still holds a pre-instance tool
 * tab (its keys haven't been renamed yet) — the sweep must not run then, or
 * a crash between the key migration and the blob save would let the next
 * boot purge the freshly moved keys.
 */
function collectLiveInstanceIds(prefix: string): { live: Set<string>; migrationPending: boolean } {
  const live = new Set<string>()
  let migrationPending = false
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key || !key.startsWith(prefix + '_') || !key.endsWith('_workspace_tabs')) continue
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || '[]')
      if (!Array.isArray(parsed)) continue
      for (const tab of parsed) {
        if (tab && tab.type === 'tool') {
          if (tab.instanceId) live.add(String(tab.instanceId))
          else migrationPending = true
        }
      }
    } catch { /* ignore malformed blobs */ }
  }
  return { live, migrationPending }
}

function orphanedInstanceKey(key: string, liveIds: Set<string>): boolean {
  const m = key.match(INSTANCE_TOKEN_RE)
  return !!m && !liveIds.has(m[1])
}

// Legacy pre-instance per-tool keys (state/prefs/etc. without an __i_ token).
// Valid only until the instance migration runs; afterwards nothing reads
// them — a closed-before-update tool reopens fresh by design (presets are
// the durable path), so the stranded keys are purged rather than leaked.
const LEGACY_TOOL_PART_RE = /_tool_.+_(state|active_preset|collapsed_groups|ai_prompt_expanded|global|ui|video_images|remix)$/

function strandedLegacyToolKey(key: string): boolean {
  return !key.includes('__i_') && LEGACY_TOOL_PART_RE.test(key)
}

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
    const { live: liveInstanceIds, migrationPending } = collectLiveInstanceIds(prefix)
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      if (shouldPurge(key, prefix)) {
        toRemove.push(key)
      } else if (!migrationPending && key.startsWith(prefix + '_') &&
        (orphanedInstanceKey(key, liveInstanceIds) || strandedLegacyToolKey(key))) {
        toRemove.push(key)
      }
    }
    for (const key of toRemove) {
      try { localStorage.removeItem(key) } catch { /* ignore */ }
    }
    if (toRemove.length > 0) {
      console.log(`[storageCleanup] purged ${toRemove.length} localStorage keys`)
    }

    // Sweep orphaned instance blobs (mask/paint) from IndexedDB too.
    // Fire-and-forget: a failure here just leaves blobs for the next boot.
    if (!migrationPending) {
      listBlobKeys().then(async (keys) => {
        const dead = keys.filter(k => k.startsWith(prefix + '_') && orphanedInstanceKey(k, liveInstanceIds))
        for (const k of dead) {
          await deleteBlob(k).catch(() => { /* ignore */ })
        }
        if (dead.length > 0) {
          console.log(`[storageCleanup] purged ${dead.length} orphaned instance blobs`)
        }
      }).catch(() => { /* ignore */ })
    }
  } catch (e) {
    console.warn('[storageCleanup] failed:', e)
  }
}
