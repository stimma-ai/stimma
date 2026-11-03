import { useAssetApi } from './useAssetApi'
import { getCurrentProfileId, useProfile } from './useProfile'
import { useMultiDevice } from './useMultiDevice'
import { getApiBase } from '../apiConfig'
import { addToast } from './useToasts'

/** One Undo contract for asset trash actions, independent of the current view. */
export function useAssetTrash() {
  const { trashMany, restoreMany } = useAssetApi()
  const { activeDeviceId } = useMultiDevice()
  const { currentDbGuid } = useProfile()

  async function trashAssetsWithUndo(assetIds: number[]) {
    const ids = [...new Set(assetIds)]
    const profile = getCurrentProfileId()
    const api = getApiBase()
    const device = activeDeviceId.value
    const database = currentDbGuid.value
    const result = await trashMany(ids)
    // The server returns only assets actually changed. Never restore an asset
    // that was already in Trash when this action began.
    const changed: number[] = result.asset_ids || []
    if (!changed.length) return result
    let restoring = false
    addToast(`Moved ${changed.length} ${changed.length === 1 ? 'asset' : 'assets'} to Trash`, 'info', 8000, {
      label: 'Undo',
      onClick: async () => {
        if (restoring) return
        if (profile !== getCurrentProfileId() || api !== getApiBase() || device !== activeDeviceId.value || (database && database !== currentDbGuid.value)) {
          addToast('Switch back to the original profile and server to restore these assets from Trash.', 'warning', 8000)
          return
        }
        restoring = true
        try {
          const restored = await restoreMany(changed)
          const count = restored.asset_ids?.length ?? 0
          if (count === changed.length) {
            addToast(`Restored ${count} ${count === 1 ? 'asset' : 'assets'}`, 'success')
          } else {
            addToast(`Restored ${count} of ${changed.length} assets. Some could not be restored; check Trash.`, 'warning', 8000)
          }
        } catch {
          restoring = false
          addToast('Could not undo. You can restore these assets from Trash.', 'error', 8000)
        }
      },
    })
    return result
  }

  return { trashAssetsWithUndo }
}
