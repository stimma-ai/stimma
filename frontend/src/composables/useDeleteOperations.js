import { computed, ref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { useWebSocket } from './useWebSocket'

// Per-operation payload from the most recent event and the profile-wide Asset
// deletion queue summary. UI progress reads only the Asset summary.
const activeDeleteOperation = ref(null)
const deleteSummary = ref(null)
let initialized = false
let clearTimer = null
// Last running summary supports the older-backend completion fallback.
let lastRunningSummary = null

export function useDeleteOperations() {
  const { getActiveDeleteOperation, retryFailedDeleteOperations } = useMediaApi()
  const { on } = useWebSocket()

  async function refreshActiveDeleteOperation() {
    try {
      const response = await getActiveDeleteOperation()
      activeDeleteOperation.value = response.operation || null
      deleteSummary.value = response.summary || null
      if (response.summary) lastRunningSummary = response.summary
    } catch (error) {
      console.error('Failed to fetch active delete operation:', error)
    }
  }

  function applyOperationUpdate(payload) {
    if (!payload) {
      activeDeleteOperation.value = null
      deleteSummary.value = null
      return
    }
    const { summary = null, ...operation } = payload
    activeDeleteOperation.value = operation
    deleteSummary.value = summary
    if (summary) lastRunningSummary = summary
  }

  function clearAfterDelay() {
    if (clearTimer) clearTimeout(clearTimer)
    clearTimer = setTimeout(() => {
      clearTimer = null
      activeDeleteOperation.value = null
      deleteSummary.value = null
      lastRunningSummary = null
      refreshActiveDeleteOperation()
    }, 5000)
  }

  if (!initialized) {
    initialized = true
    refreshActiveDeleteOperation()

    on('delete_operation_started', (data) => {
      if (data?.kind !== 'asset') return
      if (clearTimer) { clearTimeout(clearTimer); clearTimer = null }
      applyOperationUpdate(data)
    })
    on('delete_operation_progress', (data) => {
      if (data?.kind === 'asset') applyOperationUpdate(data)
    })
    on('delete_operation_completed', (data) => {
      if (data?.kind !== 'asset') return
      applyOperationUpdate(data)
      if (data?.summary?.status === 'completed') {
        clearAfterDelay()
      } else if (!data?.summary) {
        // Compatibility fallback for an older backend that omits the final
        // queue summary.
        const finished = lastRunningSummary
        deleteSummary.value = {
          status: 'completed',
          total_assets: finished?.total_assets ?? 1,
          processed_assets: finished?.total_assets ?? 1,
          failed_assets: 0,
          eta_seconds: null,
        }
        clearAfterDelay()
      }
    })
    on('delete_operation_failed', (data) => {
      if (data?.kind === 'asset') applyOperationUpdate(data)
    })
    on('websocket_reconnected', () => {
      // Re-fetch server state in case we missed events while disconnected
      refreshActiveDeleteOperation()
    })
  }

  const hasActiveDeleteOperation = computed(() => {
    // Keep the completed queue visible briefly after it drains.
    return deleteSummary.value != null
  })

  const deleteProgressPercent = computed(() => {
    const summary = deleteSummary.value
    if (!summary) return 0
    if (!summary.total_assets) return 0
    return Math.round(((summary.processed_assets || 0) / summary.total_assets) * 100)
  })

  async function retryFailedDeleteOperation() {
    if (deleteSummary.value?.status !== 'failed') return
    const response = await retryFailedDeleteOperations()
    if (response.summary) {
      deleteSummary.value = response.summary
      lastRunningSummary = response.summary
    }
    await refreshActiveDeleteOperation()
  }

  return {
    activeDeleteOperation,
    deleteSummary,
    hasActiveDeleteOperation,
    deleteProgressPercent,
    refreshActiveDeleteOperation,
    retryFailedDeleteOperation,
  }
}
