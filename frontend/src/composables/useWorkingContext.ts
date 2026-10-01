import { computed, readonly, ref, watch } from 'vue'
import { useMediaApi } from './useMediaApi'
import { getCurrentDbGuid, getCurrentProfileId } from './useProfile'
import { makeStorageKey } from '../utils/storageKeys'
import { recordEntityVisit, recentEntities } from './useRecentEntities'
import { projectIdFrom } from '../utils/workingContext'

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
  return [...projects.value].sort((a, b) => (visits.get(b.id) || Date.parse(b.updated_at || '') || 0) - (visits.get(a.id) || Date.parse(a.updated_at || '') || 0))
})
let scopeKey = ''
let request: Promise<void> | null = null

function storageKey() {
  return makeStorageKey('working_context', getCurrentProfileId() || 'default')
}

function hydrate() {
  const key = storageKey()
  if (key === scopeKey) return
  scopeKey = key
  projects.value = []
  request = null
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
  if (request) return request
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
      if (key === scopeKey) { loading.value = false; request = null }
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
