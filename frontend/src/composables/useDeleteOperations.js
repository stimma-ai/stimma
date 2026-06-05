import { computed, ref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { useWebSocket } from './useWebSocket'

const activeDeleteOperation = ref(null)
const deleteOperationError = ref(null)
let initialized = false
let clearTimer = null

export function useDeleteOperations() {
  const { getActiveDeleteOperation } = useMediaApi()
  const { on } = useWebSocket()

  async function refreshActiveDeleteOperation() {
    try {
      const response = await getActiveDeleteOperation()
      activeDeleteOperation.value = response.operation || null
      deleteOperationError.value = null
    } catch (error) {
      deleteOperationError.value = error
      console.error('Failed to fetch active delete operation:', error)
    }
  }

  function applyOperationUpdate(operation) {
    if (!operation) {
      activeDeleteOperation.value = null
      return
    }
    activeDeleteOperation.value = operation
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
      // Keep showing for a few seconds so user sees completion
      clearTimer = setTimeout(() => { activeDeleteOperation.value = null }, 5000)
    })
    on('delete_operation_failed', (data) => {
      applyOperationUpdate(data)
      clearTimer = setTimeout(() => { activeDeleteOperation.value = null }, 10000)
    })
    on('websocket_reconnected', () => {
      // Re-fetch server state in case we missed events while disconnected
      refreshActiveDeleteOperation()
    })
  }

  const hasActiveDeleteOperation = computed(() => {
    // Show as long as we have an operation (including briefly after completion)
    return activeDeleteOperation.value != null
  })

  const deleteProgressPercent = computed(() => {
    const op = activeDeleteOperation.value
    if (!op || !op.total_items) return 0
    return Math.round(((op.processed_items || 0) / op.total_items) * 100)
  })

  return {
    activeDeleteOperation,
    deleteOperationError,
    hasActiveDeleteOperation,
    deleteProgressPercent,
    refreshActiveDeleteOperation,
  }
}
