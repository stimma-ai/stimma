import { computed, readonly, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaApi } from './useMediaApi'
import { getCurrentDbGuid, getCurrentProfileId } from './useProfile'
import { makeStorageKey } from '../utils/storageKeys'
import { recordEntityVisit, recentEntities } from './useRecentEntities'
import { contextSwitchRoute, projectIdFrom } from '../utils/workingContext'
import { parseServerTime } from '../utils/timeFormat'
import { addToast } from './useToasts'
import { useWorkspaceTabs } from './useWorkspaceTabs'

export interface WorkingProject {
  id: number
  name: string | null
  updated_at?: string
  [key: string]: any
}

const activeProjectId = ref<number | null>(null)
const projects = ref<WorkingProject[]>([])
const loading = ref(false)
const error = ref('')
const visitVersion = ref(0)
const orderedProjects = computed(() => {
  void visitVersion.value
  const visits = new Map(recentEntities(60).filter(e => e.type === 'project').map(e => [Number(e.id), e.lastVisited]))
  return [...projects.value].sort((a, b) => (visits.get(b.id) || parseServerTime(b.updated_at)) - (visits.get(a.id) || parseServerTime(a.updated_at)))
})
let scopeKey = ''
let request: Promise<void> | null = null
// A change announced mid-request must not be lost to the in-flight response.
let stale = false
// When this scope's list last arrived, so remounting views can reuse it.
let loadedAt = 0
// Startup requests the list alongside settings, before the storage scope
// (which settings complete) is known. Only that profile's next load adopts it.
let prefetched: { profileId: string | null, at: number, list: Promise<WorkingProject[]> } | null = null
const PREFETCH_MAX_AGE_MS = 10_000
// Protected content requested before a lock is not handed out after it.
if (typeof window !== 'undefined') window.addEventListener('pin-auto-locked', () => { prefetched = null })

function storageKey() {
  return makeStorageKey('working_context', getCurrentProfileId() || 'default')
}

function hydrate() {
  const key = storageKey()
  if (key === scopeKey) return
  scopeKey = key
  projects.value = []
  request = null
  stale = false
  loadedAt = 0
  error.value = ''
  loading.value = false
  try {
    const stored = sessionStorage.getItem(key) ?? localStorage.getItem(key)
    activeProjectId.value = projectIdFrom(stored)
  } catch { activeProjectId.value = null }
}

function selectProject(id: number | null) {
  hydrate()
  const next = projectIdFrom(id)
  if (next != null && next !== activeProjectId.value) {
    recordEntityVisit('project', String(next), projects.value.find(p => p.id === next)?.name || '')
    visitVersion.value++
  }
  activeProjectId.value = next
  try {
    const value = activeProjectId.value == null ? '' : String(activeProjectId.value)
    // Session state keeps two windows independent; local state seeds new windows.
    sessionStorage.setItem(scopeKey, value)
    localStorage.setItem(scopeKey, value)
  } catch { /* Storage may be unavailable; in-window navigation still works. */ }
}

/** Start the project list request early; the next load for this profile uses it. */
function prefetchProjects() {
  const list = useMediaApi().getProjects() as Promise<WorkingProject[]>
  list.catch(() => {})
  prefetched = { profileId: getCurrentProfileId(), at: Date.now(), list }
}

function takePrefetched(): Promise<WorkingProject[]> | null {
  const taken = prefetched
  prefetched = null
  if (!taken || taken.profileId !== getCurrentProfileId() || Date.now() - taken.at > PREFETCH_MAX_AGE_MS) return null
  // A refused or failed early request is retried rather than reported.
  return taken.list.catch(() => useMediaApi().getProjects())
}

/**
 * Reload the project list. Mounting views pass `maxAgeMs` to accept a list
 * this scope loaded that recently (or the request already in flight) instead
 * of asking again; change notifications omit it and always reload.
 */
async function refreshProjects({ maxAgeMs }: { maxAgeMs?: number } = {}) {
  hydrate()
  if (maxAgeMs !== undefined) {
    if (request) return request
    if (loadedAt && Date.now() - loadedAt <= maxAgeMs) return
  }
  if (request) { stale = true; return request }
  const key = scopeKey
  loading.value = true
  error.value = ''
  const pending = (async () => {
    try {
      const list = await (takePrefetched() ?? useMediaApi().getProjects())
      if (key !== scopeKey) return
      projects.value = list
      loadedAt = Date.now()
      if (activeProjectId.value != null && !list.some((p: WorkingProject) => p.id === activeProjectId.value)) {
        selectProject(null)
      }
    } catch {
      if (key === scopeKey) error.value = 'Could not load projects. Try again.'
    } finally {
      if (key === scopeKey) {
        loading.value = false
        request = null
        if (stale) { stale = false; void refreshProjects() }
      }
    }
  })()
  request = pending
  return pending
}

function rememberProject(project: WorkingProject) {
  const index = projects.value.findIndex(p => p.id === project.id)
  projects.value = index < 0
    ? [project, ...projects.value]
    : projects.value.map(p => p.id === project.id ? { ...p, ...project } : p)
}

watch(() => [getCurrentProfileId(), getCurrentDbGuid()], hydrate, { immediate: true })

export function useWorkingContext() {
  hydrate()
  return {
    activeProjectId: readonly(activeProjectId),
    activeProject: computed(() => projects.value.find(p => p.id === activeProjectId.value) ?? (activeProjectId.value == null ? null : { id: activeProjectId.value, name: null })),
    projects: readonly(projects), orderedProjects, loading: readonly(loading), error: readonly(error),
    selectProject, refreshProjects, prefetchProjects, rememberProject,
  }
}

/** Enters a project (or Everything for null), keeping the current section. */
export function useContextSwitch() {
  const router = useRouter()
  const route = useRoute()
  const { findToolInstance } = useWorkspaceTabs()
  return async function switchContext(id: number | null): Promise<boolean> {
    if (activeProjectId.value === id) return true
    const target = contextSwitchRoute(route, id, findToolInstance)
    const previous = activeProjectId.value
    selectProject(id)
    try {
      const failure = await router.push(target)
      if (failure) { selectProject(previous); return false }
      return true
    } catch {
      selectProject(previous)
      addToast('Could not switch projects.', 'warning')
      return false
    }
  }
}
