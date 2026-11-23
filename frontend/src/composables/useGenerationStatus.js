import { mobileRecoveryEnabled } from './useMobileRecovery.js'
import { ref, computed } from 'vue'
import { useWebSocket } from './useWebSocket'

// Shared state across all instances - track by task type and generator instance
const activeJobsByTaskType = ref({})
const activeJobsByInstanceId = ref({})
const pendingWorkByInstanceId = ref({})
// Instances with forever mode armed. Forever mode counts as active the whole
// time it is on — the job counts above transiently hit zero between
// submissions (waiting for a slot, idle gap), and the sidebar must not read
// that as "finished". Owned by the mounted ToolView, not derived from job
// events, so a websocket drop does not clear it.
const foreverModeByInstanceId = ref({})
// Job ids currently counted in the maps above. The backend re-broadcasts
// 'generation_job_queued' when it requeues a job (provider disconnect), so
// counting raw events would inflate a count by one per requeue and leave the
// sidebar spinner stuck after the job settles. Keyed by job id, storing where
// the job was counted so the settle event decrements the same bucket.
const countedJobs = new Map()
// Live jobs by id: whose they are and whether they have started. Feeds the
// sidebar's "stalled" state — work waiting in the generation queue with
// nothing of its own running. Separate from the counts above, which also
// cover jobs whose queue event predates this connection.
const jobPhases = ref(new Map())
let initialized = false
let pendingWorkEpoch = 0
let recoverySequence = 0
// Job events seen while a reconcile snapshot is being read, in order. The
// snapshot is applied with these replayed on top, so a busy server's events
// never invalidate it and none are lost.
let journal = null

function phaseFor(job, started) {
  const instanceId = job?.generator_instance_id
  const chatId = job?.output_context_kind === 'chat' && job?.output_context_id != null ? String(job.output_context_id) : null
  return { instanceId: instanceId?.startsWith('tool-') ? instanceId : null, chatId, started }
}

function setPhase(id, phase) {
  // Only jobs that a tool or chat row can show.
  if (phase && !phase.instanceId && !phase.chatId) phase = null
  if (!phase && !jobPhases.value.has(id)) return
  const next = new Map(jobPhases.value)
  if (phase) next.set(id, phase)
  else next.delete(id)
  jobPhases.value = next
}

// Per instance/chat: jobs waiting vs started.
const activityByKey = computed(() => {
  const byKey = new Map()
  const add = (key, started) => {
    const a = byKey.get(key) || { waiting: 0, running: 0 }
    if (started) a.running++
    else a.waiting++
    byKey.set(key, a)
  }
  for (const p of jobPhases.value.values()) {
    if (p.instanceId) add(`i:${p.instanceId}`, p.started)
    if (p.chatId) add(`c:${p.chatId}`, p.started)
  }
  return byKey
})

// Instances ('i:<id>') and chats ('c:<id>') with work waiting in the queue
// and none of it moving. Raw: the sidebar holds a tab's state before showing
// it, so the handoff between one job and the next never flashes the icon.
const rawStalledKeys = computed(() => {
  const keys = new Set()
  for (const [key, a] of activityByKey.value) {
    if (a.waiting === 0 || a.running > 0) continue
    // Prompt work before submission is progress of its own.
    if (key.startsWith('i:') && (pendingWorkByInstanceId.value[key.slice(2)] || 0) > 0) continue
    keys.add(key)
  }
  return keys
})

function bucketFor(job) {
  const instanceId = job?.generator_instance_id
  return instanceId?.startsWith('tool-') ? { instanceId } : { taskType: job?.task_type || 'text-to-image' }
}

async function reconcileJobs() {
  const sequence = ++recoverySequence
  const events = []
  journal = events
  try {
    const pages = await Promise.all(['queued', 'assigned', 'processing'].map(async status => {
      const jobs = []
      for (let offset = 0; ; offset += 500) {
        const response = await fetch(`/api/generate/jobs?status=${status}&limit=500&offset=${offset}`)
        if (!response.ok) throw new Error('Could not refresh running jobs')
        const page = (await response.json()).jobs || []
        jobs.push(...page)
        if (page.length < 500) return jobs
      }
    }))
    if (sequence !== recoverySequence) return
    const active = new Map()
    const phases = new Map()
    for (const job of pages.flat()) {
      if (!active.has(job.id)) active.set(job.id, bucketFor(job))
      const phase = phaseFor(job, job.status === 'processing')
      if (phase.instanceId || phase.chatId) phases.set(job.id, phase)
    }
    // Replay by job id: idempotent whether or not the snapshot already saw an event.
    for (const event of events) {
      if (event.type === 'queued') {
        if (!active.has(event.id)) active.set(event.id, event.bucket)
        if (event.phase.instanceId || event.phase.chatId) phases.set(event.id, event.phase)
      } else if (event.type === 'started') {
        // It may have moved from queued to processing between the reads.
        if (!active.has(event.id)) active.set(event.id, event.bucket)
        const phase = phases.get(event.id) || event.phase
        if (phase.instanceId || phase.chatId) phases.set(event.id, { ...phase, started: true })
      } else {
        active.delete(event.id)
        phases.delete(event.id)
      }
    }
    jobPhases.value = phases
    const tasks = {}, instances = {}
    countedJobs.clear()
    for (const [id, bucket] of active) {
      countedJobs.set(id, bucket)
      if (bucket.instanceId) instances[bucket.instanceId] = (instances[bucket.instanceId] || 0) + 1
      else tasks[bucket.taskType] = (tasks[bucket.taskType] || 0) + 1
    }
    activeJobsByTaskType.value = tasks
    activeJobsByInstanceId.value = instances
  } catch { /* Retain the last known state until contact is restored. */ }
  finally { if (journal === events) journal = null }
}

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
      const fullJob = { ...data?.job, generator_instance_id: data?.job?.generator_instance_id || data?.generator_instance_id }
      if (jobId != null) {
        journal?.push({ type: 'queued', id: jobId, bucket: bucketFor(fullJob), phase: phaseFor(fullJob, false) })
        // A requeue (provider disconnect) puts a started job back to waiting.
        setPhase(jobId, phaseFor(fullJob, false))
      }
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

    // Already counted when queued; only its phase changes.
    onWebSocketEvent('generation_job_started', (data) => {
      const jobId = data?.job?.id
      if (jobId == null) return
      const fullJob = { ...data.job, generator_instance_id: data.job.generator_instance_id || data?.generator_instance_id }
      journal?.push({ type: 'started', id: jobId, bucket: bucketFor(fullJob), phase: phaseFor(fullJob, true) })
      const known = jobPhases.value.get(jobId)
      setPhase(jobId, known ? { ...known, started: true } : phaseFor(fullJob, true))
      // Queued before this page learned of it: count it now.
      if (!countedJobs.has(jobId)) {
        const bucket = bucketFor(fullJob)
        countedJobs.set(jobId, bucket)
        if (bucket.instanceId) incrementInstanceCount(activeJobsByInstanceId, bucket.instanceId)
        else activeJobsByTaskType.value[bucket.taskType] = (activeJobsByTaskType.value[bucket.taskType] || 0) + 1
      }
    })

    // Listen for job settle events (decrement). Only jobs we actually counted
    // may decrement, and they decrement the bucket they were counted in - a
    // settle event for a job whose queue event we never saw (queued before
    // connect, or dropped) must not eat another job's count.
    const onJobSettled = (label) => (data) => {
      const jobId = data?.job?.id
      if (jobId != null) {
        journal?.push({ type: 'settled', id: jobId })
        if (jobPhases.value.has(jobId)) setPhase(jobId, null)
      }
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

    if (mobileRecoveryEnabled) {
      window.addEventListener('profile-will-change', () => {
        recoverySequence++
        countedJobs.clear()
        activeJobsByTaskType.value = {}
        activeJobsByInstanceId.value = {}
        jobPhases.value = new Map()
      })
      window.addEventListener('profile-changed', () => { void reconcileJobs() })
    }
    // Phone disconnections retain counts until the server can reconcile them;
    // desktop clears them on disconnect. Either way the server's list of
    // running jobs is the truth once the socket is back.
    onWebSocketEvent('websocket_reconnected', () => { void reconcileJobs() })
    // The socket's first open usually fires before anything here subscribes,
    // so a page loaded mid-generation would never learn of jobs already queued.
    void reconcileJobs()
    onWebSocketEvent('websocket_disconnected', () => {
      recoverySequence++
      if (mobileRecoveryEnabled) return
      console.log('[useGenerationStatus] WebSocket disconnected - clearing all job counts')
      activeJobsByTaskType.value = {}
      activeJobsByInstanceId.value = {}
      pendingWorkByInstanceId.value = {}
      countedJobs.clear()
      jobPhases.value = new Map()
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

  // Mark/unmark an instance as forever-mode armed (see foreverModeByInstanceId).
  const setInstanceForeverMode = (instanceId, active) => {
    if (active) {
      foreverModeByInstanceId.value[instanceId] = true
    } else {
      delete foreverModeByInstanceId.value[instanceId]
    }
  }

  // Check if a specific instance ID has active jobs (for tools)
  const isInstanceActive = (instanceId) => {
    return (activeJobsByInstanceId.value[instanceId] || 0) > 0 ||
      (pendingWorkByInstanceId.value[instanceId] || 0) > 0 ||
      !!foreverModeByInstanceId.value[instanceId]
  }

  // Check if a specific tool has active jobs. Without the projectId scoping,
  // both the global and project rows in the sidebar share one lookup and spin
  // together — see instanceMatchesTool above.
  const isToolActive = (toolId, projectId = null) => {
    const hasActiveJob = Object.entries(activeJobsByInstanceId.value).some(([instanceId, count]) => {
      return count > 0 && instanceMatchesTool(instanceId, toolId, projectId)
    })
    if (hasActiveJob) return true
    const hasPendingWork = Object.entries(pendingWorkByInstanceId.value).some(([instanceId, count]) => {
      return count > 0 && instanceMatchesTool(instanceId, toolId, projectId)
    })
    if (hasPendingWork) return true
    return Object.keys(foreverModeByInstanceId.value).some(instanceId =>
      instanceMatchesTool(instanceId, toolId, projectId))
  }

  // Check activity for a specific tool-instance tab by its feedScope (the
  // tool-side token of generatorInstanceId, including any __project_N /
  // __i_K suffixes). Prefix match is exact-or-@@-delimited, so a legacy
  // (unsuffixed) scope never matches an instance-suffixed generator id.
  const isFeedScopeActive = (feedScope) => {
    const matches = ([instanceId, count]) => count > 0 && instanceMatchesFeedScope(instanceId, feedScope)
    return Object.entries(activeJobsByInstanceId.value).some(matches) ||
      Object.entries(pendingWorkByInstanceId.value).some(matches) ||
      Object.keys(foreverModeByInstanceId.value).some(instanceId =>
        instanceMatchesFeedScope(instanceId, feedScope))
  }

  // Stalled: this tool's work is waiting in the generation queue and none of
  // it is moving — no job of its own started, no prompt work under way. Any
  // instance that is moving makes the whole tab busy, not stalled. Raw state;
  // the caller holds it before showing it.
  const stalledAmong = (matches) => {
    let stalled = false
    for (const key of rawStalledKeys.value) {
      if (key.startsWith('i:') && matches(key.slice(2))) { stalled = true; break }
    }
    if (!stalled) return false
    for (const [key, a] of activityByKey.value) {
      if (a.running > 0 && key.startsWith('i:') && matches(key.slice(2))) return false
    }
    return !Object.entries(pendingWorkByInstanceId.value).some(([instanceId, count]) => count > 0 && matches(instanceId))
  }
  const isToolStalled = (toolId, projectId = null) =>
    stalledAmong(instanceId => instanceMatchesTool(instanceId, toolId, projectId))
  const isFeedScopeStalled = (feedScope) =>
    stalledAmong(instanceId => instanceMatchesFeedScope(instanceId, feedScope))
  // The chat's generations are all waiting in the queue.
  const isChatGenerationStalled = (chatId) => rawStalledKeys.value.has(`c:${chatId}`)

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
    foreverModeByInstanceId,
    beginInstanceWork,
    setInstanceForeverMode,
    isGenerating,
    isTaskTypeActive,
    isInstanceActive,
    isToolActive,
    isFeedScopeActive,
    isToolStalled,
    isFeedScopeStalled,
    isChatGenerationStalled
  }
}
