import { computed, ref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { useWebSocket } from './useWebSocket'

// Per-operation payload from the most recent event (one user action can fan
// out into many single-asset operations) and the wave-level summary the
// backend aggregates across all of them. UI reads the summary.
const activeDeleteOperation = ref(null)
const deleteSummary = ref(null)
let initialized = false
let clearTimer = null
// Last summary seen while the wave was running, so the completion state can
// show the final wave totals instead of the last operation's 1/1.
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
      if (clearTimer) { clearTimeout(clearTimer); clearTimer = null }
      applyOperationUpdate(data)
    })
    on('delete_operation_progress', (data) => applyOperationUpdate(data))
    on('delete_operation_completed', (data) => {
      applyOperationUpdate(data)
      if (!data?.summary) {
        // No summary means no queued/running/failed operations remain: the
        // whole wave is done. Show its final totals briefly, then clear.
        const finished = lastRunningSummary
        deleteSummary.value = {
          status: 'completed',
          total_items: finished?.total_items ?? data?.total_items ?? 0,
          processed_items: finished?.total_items ?? data?.processed_items ?? 0,
          failed_items: 0,
          operations_total: finished?.operations_total ?? 1,
          operations_completed: finished?.operations_total ?? 1,
          kinds: finished?.kinds ?? (data?.kind ? [data.kind] : []),
          eta_seconds: null,
        }
        clearAfterDelay()
      }
    })
    on('delete_operation_failed', (data) => {
      applyOperationUpdate(data)
    })
    on('websocket_reconnected', () => {
      // Re-fetch server state in case we missed events while disconnected
      refreshActiveDeleteOperation()
    })
  }

  const hasActiveDeleteOperation = computed(() => {
    // Show as long as we have wave state (including briefly after completion)
    return deleteSummary.value != null
  })

  const deleteProgressPercent = computed(() => {
    const summary = deleteSummary.value
    if (!summary) return 0
    if (summary.total_items) {
      return Math.round(((summary.processed_items || 0) / summary.total_items) * 100)
    }
    if (summary.operations_total) {
      return Math.round(((summary.operations_completed || 0) / summary.operations_total) * 100)
    }
    return 0
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
