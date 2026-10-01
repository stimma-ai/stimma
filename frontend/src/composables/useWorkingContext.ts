import { computed, readonly, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaApi } from './useMediaApi'
import { getCurrentDbGuid, getCurrentProfileId } from './useProfile'
import { makeStorageKey } from '../utils/storageKeys'
import { recordEntityVisit, recentEntities } from './useRecentEntities'
import { contextSwitchRoute, projectIdFrom } from '../utils/workingContext'
import { parseServerTime } from '../utils/timeFormat'
import { addToast } from './useToasts'

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

async function refreshProjects() {
  hydrate()
  if (request) { stale = true; return request }
  const key = scopeKey
  loading.value = true
  error.value = ''
  const pending = (async () => {
    try {
      const list = await useMediaApi().getProjects()
      if (key !== scopeKey) return
      projects.value = list
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
    selectProject, refreshProjects, rememberProject,
  }
}

/** Enters a project (or Everything for null), keeping the current section. */
export function useContextSwitch() {
  const router = useRouter()
  const route = useRoute()
  return async function switchContext(id: number | null): Promise<boolean> {
    if (activeProjectId.value === id) return true
    const target = contextSwitchRoute(route, id)
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
