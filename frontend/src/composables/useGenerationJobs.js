import { mobileRecoveryEnabled } from './useMobileRecovery.js'
import { ref, computed, unref, watch, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { useWebSocket } from './useWebSocket'
import { useMediaApi } from './useMediaApi'
import { useAssetApi } from './useAssetApi'
import { getCurrentProfileId } from './useProfile'
import { getApiBase } from '../apiConfig'

function getAPIBase() {
  return getApiBase()
}

// Canonical completed-history order: (completed_at DESC, id DESC). Compares the
// raw ISO strings — lexicographic order equals chronological order for ISO-8601
// and preserves the backend's full microsecond precision, so this order matches
// the backend's order=completed_at keyset paging exactly. (new Date() truncates
// to milliseconds and could disagree with the backend inside a fast burst.)
function compareCompletedDesc(a, b) {
  const atA = a.completed_at || ''
  const atB = b.completed_at || ''
  if (atA !== atB) return atA < atB ? 1 : -1
  if (typeof a.id === 'number' && typeof b.id === 'number') return b.id - a.id
  return 0
}

/**
 * Composable for managing generation jobs across different task types
 * Handles job loading, WebSocket updates, media hash loading, and marker management
 *
 * @param {Object} options
 * @param {string} options.taskType - Filter jobs by task type (e.g., 'text-to-image', 'image-to-image')
 * @param {string} options.generatorInstanceId - Optional instance ID to filter jobs by client
 * @param {import('vue').Ref<number|null>} options.activeCap - Optional reactive cap on the
 *   displayed "active" (pending/queued/assigned/processing) count, e.g. generate-forever's
 *   configured concurrency. Backend-side, a freed slot's replacement job can broadcast
 *   'generation_request_work' slightly before the outgoing job's own 'generation_job_completed'
 *   lands (finalize work is intentionally detached from slot-freeing to keep the GPU fed) -
 *   without a cap that shows as a transient N+1 tile for a fraction of a second. Null/unset
 *   means uncapped (manual, non-forever-mode generation has no such limit to enforce).
 */
export function useGenerationJobs(options = {}) {
  const { taskType = null, generatorInstanceId = null, activeCap = null } = options

  const { on: onWebSocketEvent } = useWebSocket()
  const { getMarkers, addMarkerToMedia, removeMarkerFromMedia } = useMediaApi()
  const { addMarker: addMarkerToAsset, removeMarker: removeMarkerFromAsset } = useAssetApi()

  // State
  const jobs = ref([])
  const pendingJobs = ref([])  // Client-side pending jobs (enhancing prompt)
  const mediaHashes = ref({})
  const mediaData = ref({})  // Full media objects for slideshow
  // Derived from mediaData so job tiles can gate the checkerboard on the file's
  // actual alpha channel instead of racing image-load timing.
  const mediaHasAlpha = computed(() => {
    const result = {}
    for (const [id, data] of Object.entries(mediaData.value)) {
      if (data && typeof data.has_alpha === 'boolean') result[id] = data.has_alpha
    }
    return result
  })
  const mediaMarkers = ref({})
  const mediaGenerationTimes = ref({})
  const availableMarkers = ref([])
  const dismissedJobs = ref(new Set())
  const failedMediaLoads = ref(new Set())
  // Completed jobs whose media record is still being fetched: their bar is
  // gone (status already applied) but their tile isn't shown yet.
  const mediaLoadingJobIds = ref(new Set())
  const isLoading = ref(true)

  // Batch tracking
  const batches = ref({})  // batch_id -> { total, completed, failed, output_set_id, status }
  const dismissedBatches = ref(new Set())  // batch_ids that have been dismissed

  // Post-processing chain runs: chain_run_id -> run dict (see /api/postprocessing)
  const chainRuns = ref({})
  const dismissedChainRuns = ref(new Set())

  // Live in-flight progress: job_id -> { progress, stage, previewUrl }.
  // previewUrl is an ephemeral blob: URL holding the latest diffusion preview
  // frame pushed over the websocket. These frames are transient (never
  // persisted, never library media); URLs are revoked on replacement and on
  // job settle so cached (KeepAlive) views can't accumulate leaked blobs.
  const jobProgress = ref({})
  // Monotonic frame counter per job; guards against out-of-order decodes.
  const previewSeq = new Map()

  // WebSocket unsubscribe functions
  const unsubscribers = []

  // Jobs whose post-processing chain is still running/paused: the job stays
  // "in progress" (represented by the chain bar) until the chain finishes and
  // the backend points the job at the final image.
  const jobIdsWithActiveChain = computed(() => {
    const ids = new Set()
    for (const run of Object.values(chainRuns.value)) {
      if (dismissedChainRuns.value.has(run.id)) continue
      if (['running', 'paused'].includes(run.status)) ids.add(run.job_id)
    }
    return ids
  })

  // Computed: filtered and sorted jobs list
  const allJobs = computed(() => {
    // Filter out jobs with deleted/unavailable media
    const validJobs = jobs.value.filter(j => {
      if (!j.result_media_id) return true
      return !failedMediaLoads.value.has(j.result_media_id)
    })

    // Deduplicate by job ID
    const seenIds = new Set()
    const deduplicatedJobs = validJobs.filter(j => {
      if (seenIds.has(j.id)) return false
      seenIds.add(j.id)
      return true
    })

    // Filter out dismissed failed jobs
    const filteredJobs = deduplicatedJobs.filter(j => {
      if (j.status === 'failed' && dismissedJobs.value.has(j.id)) return false
      return true
    })

    const sortByDate = (a, b) => {
      const dateA = new Date(a.completed_at || a.created_at)
      const dateB = new Date(b.completed_at || b.created_at)
      const diff = dateB - dateA
      if (diff !== 0) return diff
      // Deterministic tie-break: fast bursts can complete within the same
      // timestamp, and the slideshow pins arrival positions by index — this
      // order must never re-shuffle between recomputes. (Pending jobs have
      // string ids; leave their ties to the stable sort.)
      if (typeof a.id === 'number' && typeof b.id === 'number') return b.id - a.id
      return 0
    }

    // Include pending jobs (enhancing) in active list
    let active = [
      ...pendingJobs.value,
      ...filteredJobs.filter(j => ['queued', 'assigned', 'processing'].includes(j.status))
    ]
    // Sort BEFORE capping (same reasoning as `completed` below): keep the
    // most-recently-created entries, which drops the stale slot occupant
    // rather than the job that just replaced it.
    active = active.sort(sortByDate)
    const cap = unref(activeCap)
    if (cap && active.length > cap) {
      active = active.slice(0, cap)
    }
    const failed = filteredJobs.filter(j => j.status === 'failed')
    // Sort BEFORE capping: the cap must keep the most recently COMPLETED
    // jobs. Slicing in jobs.value (queue) order would let every newly queued
    // job evict a completed job from the middle of the list, silently shifting
    // slideshow indexes with no corresponding arrival event.
    const completed = filteredJobs
      .filter(j => j.status === 'completed' &&
        !jobIdsWithActiveChain.value.has(j.id) &&
        !mediaLoadingJobIds.value.has(j.id))
      .sort(compareCompletedDesc)
      .slice(0, 100)

    return [
      ...active,
      ...failed.sort(sortByDate),
      ...completed
    ]
  })

  const totalCompletedCount = computed(() => {
    return allJobs.value.filter(j =>
      j.status === 'completed' &&
      j.result_media_id &&
      !failedMediaLoads.value.has(j.result_media_id)
    ).length
  })

  // Computed: jobs grouped by batch
  const batchJobs = computed(() => {
    const batchGroups = {}

    // Group jobs by batch_id (skip dismissed batches)
    for (const job of jobs.value) {
      if (job.batch_id && !dismissedBatches.value.has(job.batch_id)) {
        if (!batchGroups[job.batch_id]) {
          batchGroups[job.batch_id] = {
            batch_id: job.batch_id,
            jobs: [],
            // Get batch metadata from batches ref if available
            ...(batches.value[job.batch_id] || {})
          }
        }
        batchGroups[job.batch_id].jobs.push(job)
      }
    }

    // Calculate progress for each batch
    for (const batchId in batchGroups) {
      const group = batchGroups[batchId]
      const completed = group.jobs.filter(j => j.status === 'completed').length
      const failed = group.jobs.filter(j => j.status === 'failed' || j.status === 'cancelled').length
      const inProgress = group.jobs.filter(j => ['queued', 'assigned', 'processing'].includes(j.status)).length

      // Use batch metadata if available, otherwise calculate from jobs
      group.completed = group.completed || completed
      group.failed = group.failed || failed
      group.total = group.total || group.jobs.length
      group.inProgress = inProgress

      // Get output_set_id from batches ref or from job's batch_output_set_id (persisted)
      if (!group.output_set_id) {
        // Look for batch_output_set_id on any job in the batch (it's stored on all batch jobs)
        const jobWithSetId = group.jobs.find(j => j.batch_output_set_id)
        if (jobWithSetId) {
          group.output_set_id = jobWithSetId.batch_output_set_id
        }
      }
      if (!group.result_asset_id) {
        group.result_asset_id = group.jobs.find(j => j.result_asset_id)?.result_asset_id || null
      }
      if (!group.expires_at) {
        group.expires_at = group.jobs.find(j => j.expires_at)?.expires_at || null
      }

      // Add output set data for display
      if (group.output_set_id) {
        group.output_set_hash = mediaHashes.value[group.output_set_id]
        const setData = mediaData.value[group.output_set_id]
        if (setData) {
          group.output_set_data = setData
          // Extract title from raw_metadata or vlm_caption
          if (setData.raw_metadata) {
            try {
              const parsed = typeof setData.raw_metadata === 'string'
                ? JSON.parse(setData.raw_metadata)
                : setData.raw_metadata
              group.output_set_title = parsed.title
            } catch (e) {}
          }
          group.output_set_member_count = setData.member_count
        }
      }
    }

    return batchGroups
  })

  // Load media data for a job result (stores full object for slideshow use)
  async function loadMediaHash(mediaId, markFailedOnError = true) {
    try {
      // Timeout: under generation load this endpoint can stall (connection
      // contention); a hung GET must not strand its caller forever.
      const response = await axios.get(`${getAPIBase()}/media/${mediaId}`, { timeout: 30000 })
      if (response.data && response.data.file_hash) {
        // Store full media object for slideshow
        mediaData.value = {
          ...mediaData.value,
          [mediaId]: response.data
        }
        mediaHashes.value = {
          ...mediaHashes.value,
          [mediaId]: response.data.file_hash
        }
        if (response.data.markers) {
          mediaMarkers.value = {
            ...mediaMarkers.value,
            [mediaId]: response.data.markers
          }
        }
        // Extract generation time from generation_metadata JSON
        if (response.data.generation_metadata) {
          try {
            const genMeta = typeof response.data.generation_metadata === 'string'
              ? JSON.parse(response.data.generation_metadata)
              : response.data.generation_metadata
            // generation_time can be at top level or nested in parameters
            const genTime = genMeta.generation_time ?? genMeta.parameters?.generation_time
            if (genTime) {
              mediaGenerationTimes.value = {
                ...mediaGenerationTimes.value,
                [mediaId]: genTime
              }
            }
          } catch (e) {
            // Ignore parse errors
          }
        }
        return true
      } else {
        if (markFailedOnError) {
          failedMediaLoads.value.add(mediaId)
        }
        return false
      }
    } catch (err) {
      console.error(`Failed to load media hash for ${mediaId}:`, err)
      if (err.response?.status === 404 || markFailedOnError) {
        failedMediaLoads.value.add(mediaId)
      }
      return false
    }
  }

  // Load available markers
  async function loadMarkers() {
    try {
      availableMarkers.value = await getMarkers()
    } catch (err) {
      console.error('Failed to load markers:', err)
    }
  }

  let jobLoadSequence = 0

  // Load jobs from API
  async function loadJobs(quiet = false) {
    const sequence = ++jobLoadSequence
    const profileId = getCurrentProfileId()
    try {
      // Clear all cached media data when reloading jobs (important for profile switches)
      // Media IDs are only valid within the same profile's database
      if (quiet !== true) {
        mediaHashes.value = {}
        mediaData.value = {}
        mediaMarkers.value = {}
        mediaGenerationTimes.value = {}
        failedMediaLoads.value = new Set()
        dismissedJobs.value = new Set()
        dismissedBatches.value = new Set()
        chainRuns.value = {}
        dismissedChainRuns.value = new Set()
      }

      let url = `${getAPIBase()}/generate/jobs?limit=100`
      if (generatorInstanceId) {
        url += `&generator_instance_id=${generatorInstanceId}`
      }

      const response = await axios.get(url)
      if (sequence !== jobLoadSequence || profileId !== getCurrentProfileId()) return
      let jobsList = response.data.jobs || []

      // Filter by task type if specified
      if (taskType) {
        jobsList = jobsList.filter(j => j.task_type === taskType)
      }

      jobs.value = jobsList

      // Auto-dismiss failed jobs from previous sessions
      const failedJobIds = jobs.value
        .filter(j => j.status === 'failed')
        .map(j => j.id)

      if (quiet !== true && failedJobIds.length > 0) {
        console.log(`Auto-dismissing ${failedJobIds.length} failed job(s) from previous session`)
        dismissedJobs.value = new Set(failedJobIds)
      }

      // Extract inline media data from jobs response (avoids N+1 queries)
      for (const job of jobs.value) {
        warnIfForeignJob(job, 'loadJobs')
        if (job.result_media_id && job.result_file_hash) {
          mediaHashes.value[job.result_media_id] = job.result_file_hash

          if (job.result_markers) {
            mediaMarkers.value[job.result_media_id] = job.result_markers
          }

          if (job.result_generation_time) {
            mediaGenerationTimes.value[job.result_media_id] = job.result_generation_time
          }
        }
      }

      // Fallback: parallel fetch for any jobs missing inline data (shouldn't happen normally)
      const jobsMissingMedia = jobs.value.filter(j =>
        j.result_media_id && !mediaHashes.value[j.result_media_id]
      )
      if (jobsMissingMedia.length > 0) {
        await Promise.all(jobsMissingMedia.map(j => loadMediaHash(j.result_media_id)))
      }

      // Load media hashes for batch output sets (persisted on jobs)
      const batchSetIds = new Set()
      for (const job of jobs.value) {
        if (job.batch_output_set_id && !mediaHashes.value[job.batch_output_set_id]) {
          batchSetIds.add(job.batch_output_set_id)
        }
      }
      console.log(`[useGenerationJobs] Found ${batchSetIds.size} batch output sets to load:`, [...batchSetIds])
      if (batchSetIds.size > 0) {
        const results = await Promise.all([...batchSetIds].map(async setId => {
          const success = await loadMediaHash(setId, false)
          console.log(`[useGenerationJobs] Loaded batch output set ${setId}: success=${success}, hash=${mediaHashes.value[setId]}`)
          return { setId, success }
        }))
        console.log(`[useGenerationJobs] Batch output set load results:`, results)
      }
    } catch (err) {
      console.error('Failed to load jobs:', err)
    }
  }

  // This feed is instance-scoped: loadJobs filters server-side and every job
  // broadcast carries its owning instance. A job that still lands here owned by
  // a different instance bypassed both filters — name it and its entry path
  // instead of silently rendering another tool's result in this strip.
  function warnIfForeignJob(job, via) {
    const owner = job?.generator_instance_id
    if (!generatorInstanceId || !owner || owner === generatorInstanceId) return
    console.warn(`[useGenerationJobs] foreign job in feed via ${via}`, {
      job_id: job.id,
      tool_id: job.tool_id,
      owner,
      feed: generatorInstanceId,
      result_media_id: job.result_media_id
    })
  }

  // Check if an event matches our filters
  function matchesFilters(data, via = 'ws') {
    // Check profile filter - only show jobs for current profile
    const currentProfile = getCurrentProfileId()
    if (data.job?.profile_id && data.job.profile_id !== currentProfile) {
      return false
    }
    // Check generator instance ID filter.
    // Some websocket events may omit generator_instance_id, so only reject
    // when the event explicitly has a different non-empty instance ID.
    if (generatorInstanceId && data.generator_instance_id && data.generator_instance_id !== generatorInstanceId) {
      return false
    }
    // Check task type filter
    if (taskType && data.job?.task_type !== taskType) {
      return false
    }
    warnIfForeignJob(data.job, via)
    return true
  }

  // Batches whose first arriving job already consumed a placeholder — one
  // submit shows one placeholder but a batch submit queues N jobs.
  const placeholderConsumedBatches = new Set()

  // A submit that does LLM prompt work shows a client-side 'enhancing'
  // placeholder until the real job exists. The queued-job broadcast lands
  // BEFORE the submit HTTP response resolves, so without this the strip shows
  // both the placeholder and its own queued bar for that window. Placeholders
  // can't be correlated to job ids (the id doesn't exist at placeholder time),
  // so retire the oldest one per newly arrived job/batch; the submit's own
  // removePendingJob on HTTP completion stays as the backstop.
  function consumePendingPlaceholder(job) {
    if (pendingJobs.value.length === 0) return
    if (job.batch_id) {
      if (placeholderConsumedBatches.has(job.batch_id)) return
      placeholderConsumedBatches.add(job.batch_id)
    }
    // addPendingJob unshifts, so the oldest placeholder is the last element.
    pendingJobs.value = pendingJobs.value.slice(0, -1)
  }

  function handleJobProgress(data) {
    const { job_id, progress, stage, preview_b64, preview_mime } = data
    if (job_id == null) return
    // Only track jobs this instance shows — jobs.value is already filtered
    // by the queued/started handlers, so foreign jobs never appear here.
    if (!jobs.value.some(j => j.id === job_id)) return

    const prev = jobProgress.value[job_id]
    const previewUrl = prev?.previewUrl || null
    // Progress/stage apply immediately; the frame swaps in only once decoded.
    jobProgress.value = {
      ...jobProgress.value,
      [job_id]: {
        progress,
        stage,
        previewUrl,
      },
    }

    if (!preview_b64) return
    let url
    try {
      const bin = atob(preview_b64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      url = URL.createObjectURL(new Blob([bytes], { type: preview_mime || 'image/jpeg' }))
    } catch (e) {
      return  // Malformed frame — keep the previous preview.
    }
    // Decode BEFORE swapping: replacing the <img> src with an undecoded blob
    // blanks the element for a beat (and an animated WebP restarts from a
    // blank canvas), which reads as the preview flickering out. Revoke the
    // old URL only after the new frame is ready to paint.
    //
    // Decodes can finish out of order (an animated WebP is much slower than a
    // still), so each frame carries a sequence number: a late arrival that
    // has already been superseded discards ITSELF rather than revoking the
    // newer frame that is currently painted.
    const seq = (previewSeq.get(job_id) || 0) + 1
    previewSeq.set(job_id, seq)
    const img = new Image()
    img.onload = () => {
      const cur = jobProgress.value[job_id]
      if (!cur || seq < (previewSeq.get(job_id) || 0)) {
        URL.revokeObjectURL(url)  // job settled, or a newer frame won
        return
      }
      if (cur.previewUrl) URL.revokeObjectURL(cur.previewUrl)
      jobProgress.value = {
        ...jobProgress.value,
        [job_id]: {
          ...cur,
          previewUrl: url,
        },
      }
    }
    img.onerror = () => URL.revokeObjectURL(url)
    img.src = url
  }

  function clearJobProgress(jobId) {
    previewSeq.delete(jobId)
    const entry = jobProgress.value[jobId]
    if (!entry) return
    if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl)
    const next = { ...jobProgress.value }
    delete next[jobId]
    jobProgress.value = next
  }

  function clearAllJobProgress() {
    previewSeq.clear()
    for (const entry of Object.values(jobProgress.value)) {
      if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl)
    }
    jobProgress.value = {}
  }

  // WebSocket event handlers
  function handleJobQueued(data) {
    if (!matchesFilters(data, 'job_queued')) return

    const existingIndex = jobs.value.findIndex(j => j.id === data.job.id)
    if (existingIndex === -1) {
      jobs.value.unshift(data.job)
      consumePendingPlaceholder(data.job)
    } else {
      jobs.value.splice(existingIndex, 1, data.job)
    }
  }

  async function handleJobStarted(data) {
    if (!matchesFilters(data, 'job_started')) return

    const index = jobs.value.findIndex(j => j.id === data.job.id)
    if (index !== -1) {
      jobs.value.splice(index, 1, data.job)
    } else {
      jobs.value.unshift(data.job)
      consumePendingPlaceholder(data.job)
    }
  }

  async function handleJobCompleted(data) {
    if (!matchesFilters(data, 'job_completed')) return
    clearJobProgress(data.job.id)

    // Apply the terminal status IMMEDIATELY so the in-progress bar clears in
    // lockstep with the backend slot. Gating this on the media fetch below let
    // bars pile up under load: adds are instant (queued/started handlers are
    // synchronous) but removals waited on an HTTP roundtrip, so at a
    // completion every couple of seconds the strip showed far more
    // "Generating…" bars than there were running jobs.
    const index = jobs.value.findIndex(j => j.id === data.job.id)
    if (index !== -1) {
      jobs.value.splice(index, 1, data.job)
    } else {
      // Job wasn't in list (e.g., page was refreshed during processing) - add it
      jobs.value.unshift(data.job)
    }

    // The completed TILE stays held back (via mediaLoadingJobIds in allJobs)
    // until the media record is loaded: the tile's type (image vs video) comes
    // from mediaData, and a post-processing chain can repoint an image job at
    // a video — rendering through the wrong path self-evicts on load error.
    if (data.job.result_media_id && !mediaData.value[data.job.result_media_id]) {
      mediaLoadingJobIds.value = new Set([...mediaLoadingJobIds.value, data.job.id])
      try {
        await loadMediaHash(data.job.result_media_id, true)
      } finally {
        const next = new Set(mediaLoadingJobIds.value)
        next.delete(data.job.id)
        mediaLoadingJobIds.value = next
      }
    }
  }

  async function handleJobFailed(data) {
    if (!matchesFilters(data, 'job_failed')) return
    clearJobProgress(data.job.id)

    // A job that fails fast enough (e.g. an entitlement/balance rejection
    // right at the start of processing) can have its 'failed' broadcast land
    // before this client ever added it via handleJobQueued/handleJobStarted.
    // Without this fallback the job silently never appears — it "evaporates"
    // instead of showing as a failed tile with a reason.
    const index = jobs.value.findIndex(j => j.id === data.job.id)
    if (index !== -1) {
      jobs.value.splice(index, 1, data.job)
    } else {
      jobs.value.unshift(data.job)
      consumePendingPlaceholder(data.job)
    }
  }

  function handleJobDeleted(data) {
    // For deleted events, we need to check if the job was ours
    // Since deleted event may not have full job data, check if job is in our list
    if (generatorInstanceId && data.generator_instance_id !== generatorInstanceId) {
      return
    }

    const { job_id } = data
    if (!job_id) return

    // Only remove if the job was in our list (meaning it was ours)
    const existingJob = jobs.value.find(j => j.id === job_id)
    if (existingJob) {
      jobs.value = jobs.value.filter(j => j.id !== job_id)
      clearJobProgress(job_id)
    }
  }

  function handleJobCancelled(data) {
    if (!matchesFilters(data, 'job_cancelled')) return
    if (data.job) clearJobProgress(data.job.id)

    // Keep cancelled jobs in local state so media-batch groups can account for
    // them as terminal failed cells. Standalone cancelled jobs are still omitted
    // from allJobs by its status filters.
    const index = jobs.value.findIndex(j => j.id === data.job.id)
    if (index !== -1) {
      jobs.value.splice(index, 1, data.job)
    } else if (data.job) {
      jobs.value.unshift(data.job)
    }
  }

  function handleMediaUpdated(data) {
    const { media_id, fields, media } = data
    if (!media_id || !media) return

    // Update markers if that's what changed
    if (fields.includes('markers')) {
      mediaMarkers.value = {
        ...mediaMarkers.value,
        [media_id]: media.markers || []
      }
    }

    // Update media data if we have it cached
    if (mediaData.value[media_id]) {
      mediaData.value = {
        ...mediaData.value,
        [media_id]: { ...mediaData.value[media_id], ...media }
      }
    }
  }

  function handleAutoDeleteRemoved(data) {
    const { media_id } = data
    if (!media_id) return
    jobs.value = jobs.value.map(job => (
      job.result_media_id === media_id
        ? { ...job, expires_at: null, auto_delete_at: null }
        : job
    ))
  }

  function handleMediaDeleted(data) {
    const { media_id } = data
    if (!media_id) return

    failedMediaLoads.value.add(media_id)
    delete mediaHashes.value[media_id]
    delete mediaData.value[media_id]
    delete mediaMarkers.value[media_id]
    delete mediaGenerationTimes.value[media_id]
  }

  function handleAssetsRemoved(data) {
    const currentProfile = getCurrentProfileId()
    if (data.profile_id && data.profile_id !== currentProfile) return
    const assetIds = new Set(
      data.asset_ids || (data.asset_id ? [data.asset_id] : [])
    )
    if (!assetIds.size) return
    jobs.value = jobs.value.filter(job => !assetIds.has(job.result_asset_id))
  }

  function handleBulkMediaDeleted(data) {
    const { media_ids } = data
    if (!media_ids?.length) return

    for (const media_id of media_ids) {
      failedMediaLoads.value.add(media_id)
      delete mediaHashes.value[media_id]
      delete mediaData.value[media_id]
      delete mediaMarkers.value[media_id]
      delete mediaGenerationTimes.value[media_id]
    }
  }

  // Batch event handlers
  async function handleBatchJobCompleted(data) {
    const { batch_id, completed, failed, total, output_set_id } = data
    if (!batch_id) return

    // Check profile filter
    const currentProfile = getCurrentProfileId()
    if (data.profile_id && data.profile_id !== currentProfile) return

    // Update batch state
    batches.value = {
      ...batches.value,
      [batch_id]: {
        total,
        completed,
        failed,
        output_set_id,
        status: 'in_progress'
      }
    }

    // Load/reload media hash for output set (hash changes as items are added)
    if (output_set_id) {
      await loadMediaHash(output_set_id, false)
    }
  }

  async function handleBatchCompleted(data) {
    const {
      batch_id,
      completed,
      failed,
      total,
      output_set_id,
      status,
      result_asset_id,
      expires_at,
    } = data
    if (!batch_id) return

    // Check profile filter
    const currentProfile = getCurrentProfileId()
    if (data.profile_id && data.profile_id !== currentProfile) return

    // Update batch state with final status
    batches.value = {
      ...batches.value,
      [batch_id]: {
        total,
        completed,
        failed,
        output_set_id,
        result_asset_id,
        expires_at,
        status  // 'completed', 'partial', or 'failed'
      }
    }

    if (result_asset_id) {
      jobs.value = jobs.value.map(job => (
        job.batch_id === batch_id
          ? { ...job, result_asset_id, expires_at: expires_at ?? null }
          : job
      ))
    }

    // Always reload media hash for output set (hash changes as items are added)
    if (output_set_id) {
      await loadMediaHash(output_set_id, false)
    }

    console.log(`Batch ${batch_id} completed: ${completed}/${total} succeeded, status=${status}`)
  }

  // --- Post-processing chain runs -------------------------------------------

  function trackChainRun(run) {
    chainRuns.value = { ...chainRuns.value, [run.id]: run }
    // Load thumbnails for the base, step outputs, and final
    const ids = new Set()
    if (run.base_media_id) ids.add(run.base_media_id)
    if (run.last_good_media_id) ids.add(run.last_good_media_id)
    if (run.final_media_id) ids.add(run.final_media_id)
    for (const r of run.step_results || []) {
      if (r.media_id) ids.add(r.media_id)
    }
    for (const id of ids) {
      if (!mediaHashes.value[id]) loadMediaHash(id, false)
    }
  }

  function handleChainProgress(data) {
    const run = data.chain_run
    if (!run) return
    const currentProfile = getCurrentProfileId()
    if (data.profile_id && data.profile_id !== currentProfile) return
    // Chain bars belong to the page whose base job started them
    if (generatorInstanceId && data.generator_instance_id && data.generator_instance_id !== generatorInstanceId) {
      return
    }
    trackChainRun(run)
  }

  // Restore in-flight/paused chain runs after a reload
  async function loadChainRuns() {
    try {
      const response = await axios.get(`${getAPIBase()}/postprocessing/runs?status=running,paused`)
      for (const run of response.data?.runs || []) {
        trackChainRun(run)
      }
    } catch (err) {
      console.error('Failed to load chain runs:', err)
    }
  }

  async function retryChainRun(runId) {
    try {
      await axios.post(`${getAPIBase()}/postprocessing/runs/${runId}/retry`)
    } catch (err) {
      console.error('Failed to retry chain run:', err)
    }
  }

  async function dismissChainRun(runId) {
    // Hide immediately (also suppresses any late progress broadcast for this
    // run), then soft-delete server-side so it doesn't return on reload.
    dismissedChainRuns.value.add(runId)
    dismissedChainRuns.value = new Set(dismissedChainRuns.value)
    try {
      await axios.delete(`${getAPIBase()}/postprocessing/runs/${runId}`)
    } catch (err) {
      console.error('Failed to dismiss chain run:', err)
    }
  }

  // Bars for in-flight/paused chains (newest first). On completion the chain
  // has no presence of its own — the base job's tile becomes the final image.
  const activeChainRuns = computed(() =>
    Object.values(chainRuns.value)
      .filter(r => !dismissedChainRuns.value.has(r.id) && ['running', 'paused'].includes(r.status))
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
  )

  // Public methods
  function getMediaHash(mediaId) {
    return mediaHashes.value[mediaId] || ''
  }

  function hasMarker(mediaId, markerId) {
    const markers = mediaMarkers.value[mediaId] || []
    return markers.some(m => m.id === markerId)
  }

  async function toggleMarker(mediaId, assetId, marker) {
    const has = hasMarker(mediaId, marker.id)
    try {
      if (has) {
        if (assetId) await removeMarkerFromAsset(assetId, marker.id)
        else await removeMarkerFromMedia(mediaId, marker.id)
        mediaMarkers.value = {
          ...mediaMarkers.value,
          [mediaId]: (mediaMarkers.value[mediaId] || []).filter(m => m.id !== marker.id)
        }
      } else {
        if (assetId) await addMarkerToAsset(assetId, marker.id)
        else await addMarkerToMedia(mediaId, marker.id)
        mediaMarkers.value = {
          ...mediaMarkers.value,
          [mediaId]: [...(mediaMarkers.value[mediaId] || []), marker]
        }
      }
    } catch (err) {
      console.error('Failed to toggle marker:', err)
    }
  }

  async function dismissJob(jobId) {
    try {
      await axios.delete(`${getAPIBase()}/generate/jobs/${jobId}?hard_delete=true`)
      jobs.value = jobs.value.filter(j => j.id !== jobId)
      dismissedJobs.value.add(jobId)
      dismissedJobs.value = new Set(dismissedJobs.value)
    } catch (err) {
      console.error('Failed to delete job:', err)
      dismissedJobs.value.add(jobId)
      dismissedJobs.value = new Set(dismissedJobs.value)
    }
  }

  async function retryJob(jobId) {
    try {
      // The retry endpoint re-queues the SAME job (same id, batch_id) and
      // broadcasts generation_job_queued, which updates the tile in place. Do
      // NOT dismiss/hard-delete it afterwards — that would undo the retry.
      await axios.post(`${getAPIBase()}/generate/jobs/${jobId}/retry`)
      console.log('Job retry submitted')
    } catch (err) {
      console.error('Failed to retry job:', err)
    }
  }

  // Cancel a job (queued or processing)
  async function cancelJob(jobId) {
    try {
      await axios.delete(`${getAPIBase()}/generate/jobs/${jobId}`)
      // Job will be removed via WebSocket event
      console.log(`Job ${jobId} cancelled`)
      return true
    } catch (err) {
      console.error('Failed to cancel job:', err)
      return false
    }
  }

  // Cancel all queued jobs for the current instance
  async function cancelAllQueued() {
    try {
      const params = generatorInstanceId
        ? { generator_instance_id: generatorInstanceId }
        : {}
      const response = await axios.post(`${getAPIBase()}/generate/cancel-queued`, null, { params })
      console.log(`Cancelled ${response.data?.cancelled_count || 0} queued jobs`)
      return response.data?.cancelled_count || 0
    } catch (err) {
      console.error('Failed to cancel queued jobs:', err)
      return 0
    }
  }

  // Dismiss a batch (remove from UI tracking)
  function dismissBatch(batchId) {
    console.log(`[dismissBatch] Dismissing batch ${batchId}`)

    // Add to dismissed batches set
    dismissedBatches.value.add(batchId)
    dismissedBatches.value = new Set(dismissedBatches.value)  // Trigger reactivity

    // Remove from batches tracking
    const newBatches = { ...batches.value }
    delete newBatches[batchId]
    batches.value = newBatches

    // Dismiss all jobs in this batch
    for (const job of jobs.value) {
      if (job.batch_id === batchId) {
        dismissedJobs.value.add(job.id)
      }
    }
    dismissedJobs.value = new Set(dismissedJobs.value)

    console.log(`[dismissBatch] Dismissed batches now:`, [...dismissedBatches.value])
  }

  function handleMediaLoadError(mediaId) {
    failedMediaLoads.value.add(mediaId)
    delete mediaHashes.value[mediaId]
    delete mediaData.value[mediaId]
    delete mediaMarkers.value[mediaId]
    delete mediaGenerationTimes.value[mediaId]
  }

  // Add a pending job (shown while enhancing prompt via LLM)
  function addPendingJob(prompt, params = {}) {
    const pendingId = `pending-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    const pendingJob = {
      id: pendingId,
      status: 'enhancing',
      parameters: JSON.stringify({
        prompt: prompt,
        ...params
      }),
      created_at: new Date().toISOString(),
      task_type: taskType,
      generator_instance_id: generatorInstanceId
    }
    pendingJobs.value.unshift(pendingJob)
    return pendingId
  }

  // Remove a pending job (called after real job is queued or on error)
  function removePendingJob(pendingId) {
    pendingJobs.value = pendingJobs.value.filter(j => j.id !== pendingId)
  }

  // Cancel a pending job (user clicked cancel before submission)
  function cancelPendingJob(pendingId) {
    removePendingJob(pendingId)
  }

  function getJobPrompt(job) {
    try {
      const params = JSON.parse(job.parameters)
      return params.prompt || ''
    } catch {
      return ''
    }
  }

  function getGenerationTime(job) {
    try {
      const params = JSON.parse(job.parameters)
      return params.generation_time || null
    } catch {
      return null
    }
  }

  // Memoized sorted completed jobs list to avoid re-computing on every page fetch
  const sortedCompletedJobs = computed(() => {
    return allJobs.value
      .filter(j =>
        j.status === 'completed' &&
        j.result_media_id &&
        !failedMediaLoads.value.has(j.result_media_id)
      )
      // Must match allJobs' completed ordering exactly (including the id
      // tie-break) — the slideshow's arrival pinning and page provider both
      // read this list and assume one stable order.
      .sort(compareCompletedDesc)
  })

  // Create page provider for slideshow
  // Uses pre-cached mediaData when available (already loaded during init)
  // Only fetches from API if data is missing (rare edge case)
  function projectGeneratedAsset(media, job) {
    return {
      ...media,
      asset_id: job.result_asset_id ?? media.asset_id ?? null,
      expires_at: job.expires_at ?? null,
    }
  }

  // Resolve a job to a slideshow item, using cached media data when available.
  // Failures return a placeholder rather than dropping the item: pages are
  // index-addressed, so a dropped item would shift every later slot on the page.
  async function slideshowItemForJob(job) {
    const mediaId = job.result_media_id

    if (mediaData.value[mediaId]) {
      return {
        ...projectGeneratedAsset(mediaData.value[mediaId], job),
        _slideshowItemKey: job.id
      }
    }

    try {
      const response = await axios.get(`${getAPIBase()}/media/${mediaId}`)
      // Cache it for future use
      mediaData.value = { ...mediaData.value, [mediaId]: response.data }
      return {
        ...projectGeneratedAsset(response.data, job),
        _slideshowItemKey: job.id
      }
    } catch (err) {
      console.error(`Failed to fetch media ${mediaId}:`, err)
      return { id: mediaId, file_hash: null, _placeholder: true, _slideshowItemKey: job.id }
    }
  }

  // Fetch completed jobs strictly OLDER than the in-memory window's tail, in the
  // same (completed_at DESC, id DESC) order the window itself uses. Anchoring on
  // the tail (rather than raw global offsets) keeps backend pages aligned with
  // the window under live churn: jobs newer than the tail — including completed
  // jobs the frontend is still holding back while their media prefetches — can
  // never appear here, and the set of jobs older than a given anchor only
  // changes on deletion.
  async function fetchCompletedHistoryJobs(tailJob, offset, limit) {
    const params = new URLSearchParams({
      status: 'completed',
      order: 'completed_at',
      limit: String(limit),
      offset: String(offset)
    })
    if (generatorInstanceId) params.set('generator_instance_id', generatorInstanceId)
    if (tailJob?.completed_at) {
      params.set('completed_before', tailJob.completed_at)
      if (typeof tailJob.id === 'number') params.set('completed_before_id', String(tailJob.id))
    }
    const response = await axios.get(`${getAPIBase()}/generate/jobs?${params}`)
    return response.data.jobs || []
  }

  // Slideshow page provider over the virtual completed list: the live in-memory
  // window (sortedCompletedJobs, capped) followed by backend history older than
  // its tail. Indices below the window length are served from memory so they
  // always match liveItemIds coordinates; deeper indices page the backend.
  async function fetchGeneratedImages(page, pageSize) {
    const completedJobsList = sortedCompletedJobs.value
    const windowLength = completedJobsList.length

    const start = page * pageSize
    const end = start + pageSize

    const memoryJobs = start < windowLength
      ? completedJobsList.slice(start, Math.min(end, windowLength))
      : []

    let historyJobs = []
    if (end > windowLength) {
      const tailJob = windowLength > 0 ? completedJobsList[windowLength - 1] : null
      const historyOffset = Math.max(0, start - windowLength)
      const historyLimit = end - Math.max(start, windowLength)
      historyJobs = await fetchCompletedHistoryJobs(tailJob, historyOffset, historyLimit)
    }

    return Promise.all([...memoryJobs, ...historyJobs].map(slideshowItemForJob))
  }

  // Count of visible completed jobs strictly older than the in-memory window's
  // tail. windowLength + this = the slideshow's full navigable history, so the
  // capped window never truncates the slideshow (items scrolling out of the
  // window stay reachable via backend paging instead of silently evicting).
  const completedHistoryCount = ref(0)
  let historyCountEpoch = 0
  let historyCountTimer = null

  async function refreshCompletedHistoryCount() {
    const epoch = ++historyCountEpoch
    const list = sortedCompletedJobs.value
    const tailJob = list.length > 0 ? list[list.length - 1] : null

    const params = new URLSearchParams()
    if (generatorInstanceId) params.set('generator_instance_id', generatorInstanceId)
    if (tailJob?.completed_at) {
      params.set('completed_before', tailJob.completed_at)
      if (typeof tailJob.id === 'number') params.set('completed_before_id', String(tailJob.id))
    }

    try {
      const response = await axios.get(`${getAPIBase()}/generate/jobs/completed-count?${params}`)
      if (epoch === historyCountEpoch && typeof response.data?.count === 'number') {
        completedHistoryCount.value = response.data.count
      }
    } catch (err) {
      console.error('Failed to refresh completed history count:', err)
    }
  }

  // The tail moves whenever the capped window evicts (every arrival once full)
  // or the list shrinks, and the older-than-tail count moves in step. Debounced:
  // bursts move the tail several times a second and one trailing count query is
  // enough — a briefly stale count only delays reach into the deepest history.
  watch(
    () => {
      const list = sortedCompletedJobs.value
      return list.length > 0 ? list[list.length - 1]?.id : null
    },
    () => {
      if (historyCountTimer) clearTimeout(historyCountTimer)
      historyCountTimer = setTimeout(() => {
        historyCountTimer = null
        void refreshCompletedHistoryCount()
      }, 1000)
    }
  )

  const slideshowCompletedTotal = computed(() =>
    sortedCompletedJobs.value.length + completedHistoryCount.value
  )

  // Initialize: load data and set up WebSocket listeners
  async function init() {
    isLoading.value = true

    // Subscribe to WebSocket events FIRST to avoid missing any updates during load
    console.log(`[useGenerationJobs:${taskType || 'all'}] Subscribing to WebSocket events (generatorInstanceId=${generatorInstanceId})`)
    unsubscribers.push(onWebSocketEvent('generation_job_queued', handleJobQueued))
    unsubscribers.push(onWebSocketEvent('generation_job_started', handleJobStarted))
    unsubscribers.push(onWebSocketEvent('generation_job_completed', handleJobCompleted))
    unsubscribers.push(onWebSocketEvent('generation_job_failed', handleJobFailed))
    unsubscribers.push(onWebSocketEvent('generation_job_deleted', handleJobDeleted))
    unsubscribers.push(onWebSocketEvent('generation_job_cancelled', handleJobCancelled))
    unsubscribers.push(onWebSocketEvent('generation_job_progress', handleJobProgress))
    unsubscribers.push(onWebSocketEvent('media_updated', handleMediaUpdated))
    unsubscribers.push(onWebSocketEvent('auto_delete_removed', handleAutoDeleteRemoved))
    unsubscribers.push(onWebSocketEvent('asset_deleted', handleAssetsRemoved))
    unsubscribers.push(onWebSocketEvent('asset_trashed', handleAssetsRemoved))
    unsubscribers.push(onWebSocketEvent('assets_trashed', handleAssetsRemoved))
    unsubscribers.push(onWebSocketEvent('asset_identity_deleted', handleAssetsRemoved))
    unsubscribers.push(onWebSocketEvent('media_deleted', handleMediaDeleted))
    unsubscribers.push(onWebSocketEvent('media_bulk_deleted', handleBulkMediaDeleted))
    unsubscribers.push(onWebSocketEvent('batch_job_completed', handleBatchJobCompleted))
    unsubscribers.push(onWebSocketEvent('batch_completed', handleBatchCompleted))
    unsubscribers.push(onWebSocketEvent('postprocessing_chain_progress', handleChainProgress))

    // Then load initial data (chain runs after jobs — loadJobs resets the
    // chain-run state, so populating must come second)
    await Promise.all([
      loadJobs(),
      loadMarkers()
    ])
    await loadChainRuns()

    // Retain remote work through phone suspension and reconcile on return.
    unsubscribers.push(onWebSocketEvent('websocket_reconnected', () => {
      if (mobileRecoveryEnabled) void loadJobs(true).then(() => loadChainRuns())
    }))
    unsubscribers.push(onWebSocketEvent('websocket_disconnected', () => {
      if (mobileRecoveryEnabled) return
      const deadStatuses = ['queued', 'assigned', 'processing']
      const deadCount = jobs.value.filter(j => deadStatuses.includes(j.status)).length
      if (deadCount > 0) {
        console.log(`[useGenerationJobs:${taskType}] Backend disconnected - removing ${deadCount} dead jobs`)
        jobs.value = jobs.value.filter(j => !deadStatuses.includes(j.status))
      }
      // Clear pending jobs (enhancing) - they can't complete without a backend
      if (pendingJobs.value.length > 0) {
        console.log(`[useGenerationJobs:${taskType}] Backend disconnected - clearing ${pendingJobs.value.length} pending job(s)`)
        pendingJobs.value = []
      }
      clearAllJobProgress()
    }))

    // Listen for markers config changes
    window.addEventListener('markers-changed', loadMarkers)

    isLoading.value = false
  }

  // Cleanup: unsubscribe from WebSocket events
  function cleanup() {
    unsubscribers.forEach(unsub => unsub())
    unsubscribers.length = 0
    clearAllJobProgress()
    if (historyCountTimer) {
      clearTimeout(historyCountTimer)
      historyCountTimer = null
    }
    window.removeEventListener('markers-changed', loadMarkers)
  }

  return {
    // State
    jobs,
    pendingJobs,
    allJobs,
    sortedCompletedJobs,
    mediaHashes,
    mediaData,
    mediaHasAlpha,
    mediaMarkers,
    mediaGenerationTimes,
    availableMarkers,
    dismissedJobs,
    failedMediaLoads,
    isLoading,
    totalCompletedCount,
    slideshowCompletedTotal,
    batches,
    batchJobs,
    chainRuns,
    activeChainRuns,

    // Methods
    init,
    cleanup,
    loadJobs,
    loadMediaHash,
    loadMarkers,
    getMediaHash,
    hasMarker,
    toggleMarker,
    dismissJob,
    dismissBatch,
    retryJob,
    retryChainRun,
    dismissChainRun,
    cancelJob,
    cancelAllQueued,
    handleMediaLoadError,
    getJobPrompt,
    getGenerationTime,
    fetchGeneratedImages,
    refreshCompletedHistoryCount,
    addPendingJob,
    removePendingJob,
    cancelPendingJob,

    // Live in-flight progress/preview per job
    jobProgress,

    // For external event handling (e.g., forever mode queue maintenance)
    handleJobQueued,
    handleJobStarted,
    handleJobCompleted,
    handleJobFailed,
    handleJobCancelled
  }
}
