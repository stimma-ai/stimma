/**
 * One-time migration of persisted UI state from debug-scoped storage keys.
 *
 * Before the Tauri shell forwarded --bundle-id to the backend, official builds
 * reported the debug bundle id, so every namespaced localStorage key and
 * IndexedDB blob (see storageKeys.ts: `stimma_{bundleId}_{sandbox}_...`) was
 * written under `ai.stimma.stimma.debug`. The first launch of a fixed build
 * looks under its real bundle id and finds nothing — sidebar, tool state,
 * workspace tabs all appear wiped, though the data is still present under the
 * old prefix.
 *
 * Runs from setBundleId() before anything reads namespaced keys. Keys are
 * renamed (copy, then delete); existing keys under the new prefix are never
 * overwritten. Each app channel has its own WebView storage, so debug-prefixed
 * entries inside this origin can only have been written by this same install.
 */

const DEBUG_BUNDLE_ID = 'ai.stimma.stimma.debug'

export function migrateDebugScopedStorage(bundleId: string, sandbox: string): void {
  if (!bundleId || bundleId === DEBUG_BUNDLE_ID) return
  const oldPrefix = `stimma_${DEBUG_BUNDLE_ID}_${sandbox}_`
  const newPrefix = `stimma_${bundleId}_${sandbox}_`

  try {
    const marker = `${newPrefix}migrated_from_debug`
    if (localStorage.getItem(marker) === null) {
      const toMove: string[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (key && key.startsWith(oldPrefix)) toMove.push(key)
      }
      for (const key of toMove) {
        const value = localStorage.getItem(key)
        const newKey = newPrefix + key.slice(oldPrefix.length)
        if (value !== null && localStorage.getItem(newKey) === null) {
          localStorage.setItem(newKey, value)
        }
        localStorage.removeItem(key)
      }
      localStorage.setItem(marker, '1')
      if (toMove.length > 0) {
        console.log(`[storageMigration] moved ${toMove.length} localStorage keys from debug-scoped prefix`)
      }
    }

    // Mask/paint blobs use the same prefix in IndexedDB. Best-effort and
    // resumable: its own completion marker, so a launch interrupted mid-copy
    // finishes the job next boot.
    const blobMarker = `${newPrefix}migrated_from_debug_blobs`
    if (localStorage.getItem(blobMarker) === null) {
      void migrateDebugScopedBlobs(oldPrefix, newPrefix, blobMarker)
    }
  } catch (e) {
    console.warn('[storageMigration] failed:', e)
  }
}

async function migrateDebugScopedBlobs(oldPrefix: string, newPrefix: string, marker: string): Promise<void> {
  try {
    // Lazy import keeps IndexedDB out of module-init (and out of node tests).
    const { listBlobKeys, getBlob, putBlob, deleteBlob } = await import('./blobStorage')
    const keys = await listBlobKeys(oldPrefix)
    let moved = 0
    for (const key of keys) {
      const newKey = newPrefix + key.slice(oldPrefix.length)
      const value = await getBlob(key)
      if (value !== null && (await getBlob(newKey)) === null) {
        await putBlob(newKey, value)
      }
      await deleteBlob(key)
      moved++
    }
    localStorage.setItem(marker, '1')
    if (moved > 0) {
      console.log(`[storageMigration] moved ${moved} blobs from debug-scoped prefix`)
    }
  } catch (e) {
    console.warn('[storageMigration] blob migration failed:', e)
  }
}
