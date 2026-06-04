import { ref, computed } from 'vue'
import { useWebSocket } from './useWebSocket'

// Shared state across all instances - track by task type and generator instance
const activeJobsByTaskType = ref({})
const activeJobsByInstanceId = ref({})
let initialized = false

/**
 * Composable for tracking active generation jobs
 * Returns reactive state that shows if generation is in progress
 */
export function useGenerationStatus() {
  const { on: onWebSocketEvent } = useWebSocket()

  // Initialize WebSocket listeners once
  if (!initialized) {
    initialized = true

    // Listen for job queue/start events (increment)
    onWebSocketEvent('generation_job_queued', (data) => {
      const taskType = data?.job?.task_type || 'text-to-image'
      // Use job's generator_instance_id, falling back to top-level (both are sent by backend)
      const instanceId = data?.job?.generator_instance_id || data?.generator_instance_id
      const isToolJob = instanceId && instanceId.startsWith('tool-')

      // Track by instance ID (for tools) - takes precedence
      if (isToolJob) {
        if (!activeJobsByInstanceId.value[instanceId]) {
          activeJobsByInstanceId.value[instanceId] = 0
        }
        activeJobsByInstanceId.value[instanceId]++
        console.log(`[useGenerationStatus] Job queued: instanceId=${instanceId}, count=${activeJobsByInstanceId.value[instanceId]}`)
      } else {
        // Only track by task type if NOT a tool job
        if (!activeJobsByTaskType.value[taskType]) {
          activeJobsByTaskType.value[taskType] = 0
        }
        activeJobsByTaskType.value[taskType]++
      }
    })

    onWebSocketEvent('generation_job_started', () => {
      // Already counted when queued, no need to increment
    })

    // Listen for job completion/failure events (decrement)
    onWebSocketEvent('generation_job_completed', (data) => {
      const taskType = data?.job?.task_type || 'text-to-image'
      // Use job's generator_instance_id, falling back to top-level (both are sent by backend)
      const instanceId = data?.job?.generator_instance_id || data?.generator_instance_id
      const isToolJob = instanceId && instanceId.startsWith('tool-')

      if (isToolJob) {
        const prevCount = activeJobsByInstanceId.value[instanceId] || 0
        if (prevCount > 0) {
          activeJobsByInstanceId.value[instanceId] = prevCount - 1
          console.log(`[useGenerationStatus] Job completed: instanceId=${instanceId}, count=${prevCount}->${activeJobsByInstanceId.value[instanceId]}`)
        }
      } else {
        if (activeJobsByTaskType.value[taskType]) {
          activeJobsByTaskType.value[taskType] = Math.max(0, activeJobsByTaskType.value[taskType] - 1)
        }
      }
    })

    onWebSocketEvent('generation_job_failed', (data) => {
      const taskType = data?.job?.task_type || 'text-to-image'
      // Use job's generator_instance_id, falling back to top-level (both are sent by backend)
      const instanceId = data?.job?.generator_instance_id || data?.generator_instance_id
      const isToolJob = instanceId && instanceId.startsWith('tool-')

      if (isToolJob) {
        const prevCount = activeJobsByInstanceId.value[instanceId] || 0
        if (prevCount > 0) {
          activeJobsByInstanceId.value[instanceId] = prevCount - 1
          console.log(`[useGenerationStatus] Job failed: instanceId=${instanceId}, count=${prevCount}->${activeJobsByInstanceId.value[instanceId]}`)
        } else {
          console.warn(`[useGenerationStatus] Job failed but no count to decrement: instanceId=${instanceId}`)
        }
      } else {
        if (activeJobsByTaskType.value[taskType]) {
          activeJobsByTaskType.value[taskType] = Math.max(0, activeJobsByTaskType.value[taskType] - 1)
        }
      }
    })

    onWebSocketEvent('generation_job_cancelled', (data) => {
      const taskType = data?.job?.task_type || 'text-to-image'
      // Use job's generator_instance_id, falling back to top-level (both are sent by backend)
      const instanceId = data?.job?.generator_instance_id || data?.generator_instance_id
      const isToolJob = instanceId && instanceId.startsWith('tool-')

      if (isToolJob) {
        const prevCount = activeJobsByInstanceId.value[instanceId] || 0
        if (prevCount > 0) {
          activeJobsByInstanceId.value[instanceId] = prevCount - 1
          console.log(`[useGenerationStatus] Job cancelled: instanceId=${instanceId}, count=${prevCount}->${activeJobsByInstanceId.value[instanceId]}`)
        }
      } else {
        if (activeJobsByTaskType.value[taskType]) {
          activeJobsByTaskType.value[taskType] = Math.max(0, activeJobsByTaskType.value[taskType] - 1)
        }
      }
    })

    // Clear all counts on disconnect - jobs are dead
    onWebSocketEvent('websocket_disconnected', () => {
      console.log('[useGenerationStatus] WebSocket disconnected - clearing all job counts')
      activeJobsByTaskType.value = {}
      activeJobsByInstanceId.value = {}
    })
  }

  // Check if any jobs are active (backwards compatible)
  const isGenerating = () => {
    return Object.values(activeJobsByTaskType.value).some(count => count > 0)
  }

  // Check if a specific task type has active jobs
  const isTaskTypeActive = (taskType) => {
    return (activeJobsByTaskType.value[taskType] || 0) > 0
  }

  // Check if a specific instance ID has active jobs (for tools)
  const isInstanceActive = (instanceId) => {
    return (activeJobsByInstanceId.value[instanceId] || 0) > 0
  }

  // Check if a specific tool has active jobs
  // Handles formats: tool-{id}, tool-{id}@@{uuid} (new), tool-{id}-{uuid} (legacy)
  // Note: toolId (full_tool_id) uses colons, but generator_instance_id uses underscores
  const isToolActive = (toolId) => {
    // Convert colons to underscores to match the storage-safe format used in generator_instance_id
    const storageToolId = toolId.replace(/:/g, '_')
    const prefix = `tool-${storageToolId}`
    return Object.entries(activeJobsByInstanceId.value).some(([instanceId, count]) => {
      if (count <= 0) return false
      // Exact match (no tab GUID suffix)
      if (instanceId === prefix) return true
      // New format: tool-{id}@@{uuid} - use @@ separator to avoid ambiguity with hyphens in tool IDs
      if (instanceId.startsWith(`${prefix}@@`)) return true
      // Legacy format: tool-{id}-{uuid} - only match if followed by valid UUID pattern
      // UUID format: 8-4-4-4-12 hex chars (e.g., 550e8400-e29b-41d4-a716-446655440000)
      const legacyMatch = instanceId.match(new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$`, 'i'))
      return !!legacyMatch
    })
  }

  // Computed for total active jobs (backwards compatible)
  const activeJobCount = computed(() => {
    return Object.values(activeJobsByTaskType.value).reduce((sum, count) => sum + count, 0)
  })

  return {
    activeJobCount,
    activeJobsByTaskType,
    activeJobsByInstanceId,
    isGenerating,
    isTaskTypeActive,
    isInstanceActive,
    isToolActive
  }
}
