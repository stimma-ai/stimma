/**
 * Background work: library processing phases (metadata, CLIP, faces,
 * captions), permanent-delete progress and system warnings, as one shared
 * state. The desktop top bar and the compact header both read it; whichever
 * mounts first calls `start()` once and the websocket keeps it fresh.
 */
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { useWebSocket } from './useWebSocket'
import { useDeleteOperations } from './useDeleteOperations'
import { captioningEnabledRef } from '../appConfig'
import { makeGlobalKey } from '../utils/storageKeys'

const API_URL = import.meta.env.VITE_API_URL || ''

export const PHASE_NAMES = {
  metadata: 'Reading Files',
  clip: 'Visual Indexing',
  face_detection: 'Face Analysis',
  vlm_caption: 'Visual Analysis',
}

const stats = ref({
  metadata: { pending: 0, processing: 0, completed: 0, failed: 0 },
  clip: { pending: 0, processing: 0, completed: 0, failed: 0 },
  face_detection: { pending: 0, processing: 0, completed: 0, failed: 0 },
  vlm_caption: { pending: 0, processing: 0, completed: 0, failed: 0 },
})
const systemWarnings = ref([])
const statsLoading = ref(true)
const isPaused = ref(false)
const rescanning = ref(false)
const retryingDeletion = ref(false)

// Failed-items list (one phase at a time)
const failedOpen = ref(false)
const failedPhase = ref('')
const failedItems = ref([])
const loadingFailed = ref(false)
const retrying = ref(false)
const trashing = ref(false)

let started = false

async function fetchStats() {
  try {
    const response = await axios.get(`${API_URL}/api/processing/stats`)
    stats.value = response.data.phase_stats
    statsLoading.value = false
  } catch (error) {
    console.error('Failed to fetch processing stats:', error)
  }
}

async function fetchPauseStatus() {
  try {
    const response = await axios.get(`${API_URL}/api/processing/status`)
    isPaused.value = response.data.paused
  } catch (error) {
    console.error('Failed to fetch pause status:', error)
  }
}

function isSystemWarningDismissed(type) {
  return localStorage.getItem(makeGlobalKey('dismissed_warning', type)) === 'true'
}

function addSystemWarning(w) {
  if (isSystemWarningDismissed(w.type)) return
  if (systemWarnings.value.some((x) => x.type === w.type)) return
  systemWarnings.value.push({
    type: w.type,
    title: w.title || 'System Warning',
    message: w.message || '',
    action_url: w.action_url || '',
    action_label: w.action_label || '',
  })
}

async function fetchSystemWarnings() {
  // Broadcasts are missed if the websocket reconnects at the wrong moment,
  // so also check current state directly.
  try {
    const response = await axios.get(`${API_URL}/api/processing/warnings`)
    for (const warning of response.data?.warnings || []) addSystemWarning(warning)
  } catch (error) {
    console.error('Failed to fetch system warnings:', error)
  }
}

function dismissSystemWarning(type) {
  localStorage.setItem(makeGlobalKey('dismissed_warning', type), 'true')
  systemWarnings.value = systemWarnings.value.filter((w) => w.type !== type)
}

async function openSystemWarningAction(url) {
  if (!url) return
  try {
    const { desktop } = await import('../desktop')
    await desktop.openExternal(url)
  } catch (error) {
    console.error('Failed to open system warning action:', error)
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

async function togglePause() {
  try {
    if (isPaused.value) {
      await axios.post(`${API_URL}/api/processing/resume`)
      isPaused.value = false
    } else {
      await axios.post(`${API_URL}/api/processing/pause`)
      isPaused.value = true
    }
  } catch (error) {
    console.error('Failed to toggle pause:', error)
  }
}

async function triggerRescan() {
  rescanning.value = true
  try {
    await axios.post(`${API_URL}/api/rescan`)
    await fetchStats()
  } catch (error) {
    console.error('Failed to trigger rescan:', error)
  } finally {
    rescanning.value = false
  }
}

function getTotalForPhase(phase) {
  const p = stats.value[phase]
  if (!p) return 0
  return (p.pending || 0) + (p.processing || 0) + (p.completed || 0) + (p.failed || 0)
}

function getProgressPercent(phase) {
  const total = getTotalForPhase(phase)
  if (total === 0) return 0
  return Math.round(((stats.value[phase]?.completed || 0) / total) * 100)
}

function hasPendingWork(phase) {
  const p = stats.value[phase]
  if (!p) return false
  return getTotalForPhase(phase) > (p.completed || 0)
}

const activePhases = computed(() =>
  Object.entries(stats.value)
    .filter(([key]) => key !== 'vlm_caption' || captioningEnabledRef.value)
    .map(([, phase]) => phase),
)
const totalPending = computed(() => activePhases.value.reduce((s, p) => s + (p.pending || 0), 0))
const totalProcessing = computed(() => activePhases.value.reduce((s, p) => s + (p.processing || 0), 0))
const totalCompleted = computed(() => activePhases.value.reduce((s, p) => s + (p.completed || 0), 0))
const totalFailed = computed(() => activePhases.value.reduce((s, p) => s + (p.failed || 0), 0))

// Failed items
async function showFailedItems(phase) {
  failedPhase.value = phase
  failedOpen.value = true
  loadingFailed.value = true
  failedItems.value = []
  try {
    const response = await axios.get(`${API_URL}/api/processing/failed/${phase}`)
    failedItems.value = response.data.items
  } catch (error) {
    console.error('Failed to fetch failed items:', error)
  } finally {
    loadingFailed.value = false
  }
}

function closeFailedItems() {
  failedOpen.value = false
  failedItems.value = []
  failedPhase.value = ''
}

async function retryAll() {
  retrying.value = true
  try {
    await axios.post(`${API_URL}/api/processing/retry/${failedPhase.value}`)
    await showFailedItems(failedPhase.value)
    await fetchStats()
  } catch (error) {
    console.error('Failed to retry items:', error)
  } finally {
    retrying.value = false
  }
}

async function retryItem(itemId) {
  retrying.value = true
  try {
    await axios.post(`${API_URL}/api/processing/retry/${failedPhase.value}`, { item_ids: [itemId] })
    await showFailedItems(failedPhase.value)
    await fetchStats()
  } catch (error) {
    console.error(`Failed to retry item ${itemId}:`, error)
  } finally {
    retrying.value = false
  }
}

async function trashAll() {
  trashing.value = true
  try {
    await axios.post(`${API_URL}/api/processing/trash/${failedPhase.value}`)
    await fetchStats()
    await showFailedItems(failedPhase.value)
    if (failedItems.value.length === 0) closeFailedItems()
  } catch (error) {
    console.error('Failed to trash items:', error)
  } finally {
    trashing.value = false
  }
}

export function useBackgroundWork() {
  const { connected: wsConnected, on: wsOn } = useWebSocket()
  const del = useDeleteOperations()

  async function retryDeletion() {
    retryingDeletion.value = true
    try {
      await del.retryFailedDeleteOperation()
    } finally {
      retryingDeletion.value = false
    }
  }

  const isDeleteRunning = computed(() => del.deleteSummary.value?.status === 'running')
  const hasDeleteFailed = computed(() => del.deleteSummary.value?.status === 'failed')
  const hasDeleteCompleted = computed(() => del.deleteSummary.value?.status === 'completed')
  const deleteTotalCount = computed(() => del.deleteSummary.value?.total_assets || 0)
  const deleteDoneCount = computed(() => del.deleteSummary.value?.processed_assets || 0)
  const deleteOperationLabel = computed(() => {
    const summary = del.deleteSummary.value
    if (!summary) return ''
    if (summary.status === 'completed') return 'Complete'
    if (summary.status === 'failed') return `${summary.failed_assets || 0} failed`
    return `${deleteTotalCount.value - deleteDoneCount.value} remaining`
  })

  const isActivelyProcessing = computed(() => totalProcessing.value > 0)
  const hasIncompleteWork = computed(() => totalPending.value > 0 || totalProcessing.value > 0)
  // Only true when there is work happening or errors to handle; idle = hidden.
  const hasActiveWork = computed(() =>
    totalPending.value > 0 || totalProcessing.value > 0 || totalFailed.value > 0
    || systemWarnings.value.length > 0 || del.hasActiveDeleteOperation.value,
  )
  const progressTitle = computed(() => {
    if (hasDeleteFailed.value) return 'Permanent deletion failed - click for details'
    if (hasDeleteCompleted.value) return 'Permanent deletion complete - click for details'
    if (isDeleteRunning.value) return 'Permanent deletion in progress - click for details'
    if (isPaused.value && hasIncompleteWork.value) return 'Processing paused - click for details'
    if (isActivelyProcessing.value) return 'Processing in progress - click for details'
    if (totalFailed.value > 0) return `${totalFailed.value} failed items - click for details`
    if (totalPending.value > 0) return `${totalPending.value} items pending - click for details`
    return 'Click for processing details'
  })

  /** Idempotent: fetch everything once and keep it fresh over the websocket. */
  function start() {
    if (started) return
    started = true
    fetchStats()
    fetchPauseStatus()
    del.refreshActiveDeleteOperation()
    fetchSystemWarnings()
    // The broadcast aggregates across profiles; use it as a trigger to
    // re-fetch profile-specific stats.
    wsOn('processing_stats', () => fetchStats())
    wsOn('system_warning', (data) => addSystemWarning(data))
    wsOn('system_warning_cleared', (data) => {
      systemWarnings.value = systemWarnings.value.filter((w) => w.type !== data.type)
    })
    // Backend went away and came back: reload.
    watch(wsConnected, (connected, wasConnected) => {
      if (connected && wasConnected === false) {
        fetchStats()
        fetchPauseStatus()
        del.refreshActiveDeleteOperation()
      }
    })
  }

  return {
    stats, systemWarnings, statsLoading, isPaused, rescanning, retryingDeletion,
    totalPending, totalProcessing, totalCompleted, totalFailed,
    hasActiveWork, isActivelyProcessing, hasIncompleteWork, progressTitle,
    deleteSummary: del.deleteSummary, deleteProgressPercent: del.deleteProgressPercent,
    isDeleteRunning, hasDeleteFailed, hasDeleteCompleted, deleteTotalCount, deleteDoneCount, deleteOperationLabel,
    failedOpen, failedPhase, failedItems, loadingFailed, retrying, trashing,
    failedTitle: computed(() => PHASE_NAMES[failedPhase.value] || failedPhase.value),
    start, fetchStats, fetchPauseStatus, togglePause, triggerRescan, retryDeletion,
    getTotalForPhase, getProgressPercent, hasPendingWork,
    dismissSystemWarning, openSystemWarningAction,
    showFailedItems, closeFailedItems, retryAll, retryItem, trashAll,
  }
}
