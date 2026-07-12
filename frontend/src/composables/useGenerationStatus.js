import { ref, computed } from 'vue'
import { useWebSocket } from './useWebSocket'

// Shared state across all instances - track by task type and generator instance
const activeJobsByTaskType = ref({})
const activeJobsByInstanceId = ref({})
const pendingWorkByInstanceId = ref({})
// Job ids currently counted in the maps above. The backend re-broadcasts
// 'generation_job_queued' when it requeues a job (provider disconnect), so
// counting raw events would inflate a count by one per requeue and leave the
// sidebar spinner stuck after the job settles. Keyed by job id, storing where
// the job was counted so the settle event decrements the same bucket.
const countedJobs = new Map()
let initialized = false
let pendingWorkEpoch = 0

function incrementInstanceCount(counts, instanceId) {
  counts.value[instanceId] = (counts.value[instanceId] || 0) + 1
}

function decrementInstanceCount(counts, instanceId) {
  const prevCount = counts.value[instanceId] || 0
  if (prevCount <= 1) {
    delete counts.value[instanceId]
  } else {
    counts.value[instanceId] = prevCount - 1
  }
}

// Check whether a generator_instance_id belongs to a tool (optionally scoped
// to a project). Handles formats: tool-{id}, tool-{id}@@{uuid} (new),
// tool-{id}-{uuid} (legacy). toolId (full_tool_id) uses colons, but
// generator_instance_id uses underscores. Project-scoped ToolViews build
// their generator_instance_id with a `__project_{id}` suffix (see
// ToolView.vue projectSuffix/toolIdForStorage), so the global instance and a
// project-scoped instance of the same tool are distinct.
export function instanceMatchesTool(instanceId, toolId, projectId = null) {
  const storageToolId = toolId.replace(/:/g, '_')
  const projectSuffix = projectId ? `__project_${projectId}` : ''
  const prefix = `tool-${storageToolId}${projectSuffix}`
  // Exact match (no tab GUID suffix)
  if (instanceId === prefix) return true
  // New format: tool-{id}@@{uuid} - use @@ separator to avoid ambiguity with hyphens in tool IDs
  if (instanceId.startsWith(`${prefix}@@`)) return true
  // Legacy format: tool-{id}-{uuid} - only match if followed by valid UUID pattern
  // UUID format: 8-4-4-4-12 hex chars (e.g., 550e8400-e29b-41d4-a716-446655440000)
  const legacyMatch = instanceId.match(new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$`, 'i'))
  return !!legacyMatch
}

export function instanceMatchesFeedScope(instanceId, feedScope) {
  if (!instanceId || !feedScope) return false
  const prefix = `tool-${feedScope}`
  return instanceId === prefix || instanceId.startsWith(`${prefix}@@`)
}

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
      const jobId = data?.job?.id
      const taskType = data?.job?.task_type || 'text-to-image'
      // Use job's generator_instance_id, falling back to top-level (both are sent by backend)
      const instanceId = data?.job?.generator_instance_id || data?.generator_instance_id
      const isToolJob = instanceId && instanceId.startsWith('tool-')

      // Requeue re-broadcast for a job we already counted - not new work.
      if (jobId != null && countedJobs.has(jobId)) return
      if (jobId != null) {
        countedJobs.set(jobId, isToolJob ? { instanceId } : { taskType })
      }

      // Track by instance ID (for tools) - takes precedence
      if (isToolJob) {
        incrementInstanceCount(activeJobsByInstanceId, instanceId)
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

    // Listen for job settle events (decrement). Only jobs we actually counted
    // may decrement, and they decrement the bucket they were counted in - a
    // settle event for a job whose queue event we never saw (queued before
    // connect, or dropped) must not eat another job's count.
    const onJobSettled = (label) => (data) => {
      const jobId = data?.job?.id
      const taskType = data?.job?.task_type || 'text-to-image'
      // Use job's generator_instance_id, falling back to top-level (both are sent by backend)
      const instanceId = data?.job?.generator_instance_id || data?.generator_instance_id
      const isToolJob = instanceId && instanceId.startsWith('tool-')

      let counted = null
      if (jobId != null) {
        counted = countedJobs.get(jobId)
        if (!counted) {
          console.warn(`[useGenerationStatus] Job ${label} but job was never counted: jobId=${jobId}, instanceId=${instanceId}`)
          return
        }
        countedJobs.delete(jobId)
      }

      if (counted ? counted.instanceId : isToolJob) {
        const countedInstanceId = counted?.instanceId || instanceId
        const prevCount = activeJobsByInstanceId.value[countedInstanceId] || 0
        if (prevCount > 0) {
          decrementInstanceCount(activeJobsByInstanceId, countedInstanceId)
          console.log(`[useGenerationStatus] Job ${label}: instanceId=${countedInstanceId}, count=${prevCount}->${activeJobsByInstanceId.value[countedInstanceId]}`)
        }
      } else {
        const countedTaskType = counted?.taskType || taskType
        if (activeJobsByTaskType.value[countedTaskType]) {
          activeJobsByTaskType.value[countedTaskType] = Math.max(0, activeJobsByTaskType.value[countedTaskType] - 1)
        }
      }
    }

    onWebSocketEvent('generation_job_completed', onJobSettled('completed'))
    onWebSocketEvent('generation_job_failed', onJobSettled('failed'))
    onWebSocketEvent('generation_job_cancelled', onJobSettled('cancelled'))

    // Clear all counts on disconnect - jobs are dead
    onWebSocketEvent('websocket_disconnected', () => {
      console.log('[useGenerationStatus] WebSocket disconnected - clearing all job counts')
      activeJobsByTaskType.value = {}
      activeJobsByInstanceId.value = {}
      pendingWorkByInstanceId.value = {}
      countedJobs.clear()
      pendingWorkEpoch++
    })
  }

  // Track pre-submit work that belongs to a ToolView, such as prompt
  // enhancement/translation before the backend emits generation_job_queued.
  const beginInstanceWork = (instanceId) => {
    incrementInstanceCount(pendingWorkByInstanceId, instanceId)
    const epoch = pendingWorkEpoch
    let finished = false
    return () => {
      if (finished) return
      finished = true
      if (epoch !== pendingWorkEpoch) return
      decrementInstanceCount(pendingWorkByInstanceId, instanceId)
    }
  }

  // Check if any jobs are active (backwards compatible)
  const isGenerating = () => {
    return Object.values(activeJobsByTaskType.value).some(count => count > 0) ||
      Object.values(pendingWorkByInstanceId.value).some(count => count > 0)
  }

  // Check if a specific task type has active jobs
  const isTaskTypeActive = (taskType) => {
    return (activeJobsByTaskType.value[taskType] || 0) > 0
  }

  // Check if a specific instance ID has active jobs (for tools)
  const isInstanceActive = (instanceId) => {
    return (activeJobsByInstanceId.value[instanceId] || 0) > 0 ||
      (pendingWorkByInstanceId.value[instanceId] || 0) > 0
  }

  // Check if a specific tool has active jobs. Without the projectId scoping,
  // both the global and project rows in the sidebar share one lookup and spin
  // together — see instanceMatchesTool above.
  const isToolActive = (toolId, projectId = null) => {
    const hasActiveJob = Object.entries(activeJobsByInstanceId.value).some(([instanceId, count]) => {
      return count > 0 && instanceMatchesTool(instanceId, toolId, projectId)
    })
    if (hasActiveJob) return true
    return Object.entries(pendingWorkByInstanceId.value).some(([instanceId, count]) => {
      return count > 0 && instanceMatchesTool(instanceId, toolId, projectId)
    })
  }

  // Check activity for a specific tool-instance tab by its feedScope (the
  // tool-side token of generatorInstanceId, including any __project_N /
  // __i_K suffixes). Prefix match is exact-or-@@-delimited, so a legacy
  // (unsuffixed) scope never matches an instance-suffixed generator id.
  const isFeedScopeActive = (feedScope) => {
    const matches = ([instanceId, count]) => count > 0 && instanceMatchesFeedScope(instanceId, feedScope)
    return Object.entries(activeJobsByInstanceId.value).some(matches) ||
      Object.entries(pendingWorkByInstanceId.value).some(matches)
  }

  // Computed for total active jobs (backwards compatible)
  const activeJobCount = computed(() => {
    return Object.values(activeJobsByTaskType.value).reduce((sum, count) => sum + count, 0) +
      Object.values(pendingWorkByInstanceId.value).reduce((sum, count) => sum + count, 0)
  })

  return {
    activeJobCount,
    activeJobsByTaskType,
    activeJobsByInstanceId,
    pendingWorkByInstanceId,
    beginInstanceWork,
    isGenerating,
    isTaskTypeActive,
    isInstanceActive,
    isToolActive,
    isFeedScopeActive
  }
}
