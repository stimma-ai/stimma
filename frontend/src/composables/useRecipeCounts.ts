import { reactive, computed, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from './useWebSocket'
import { useRecipesApi } from './useRecipesApi'

// Singleton: pending task count + execution_state per recipe id. Read by
// sidebar tab badges and landing-view RecipeCards so every surface agrees
// without opening per-recipe state.db. The counter is maintained
// server-side (recipes.pending_task_count, denormalized) and flows in via
// recipe_task_created / recipe_task_resolved payloads; the execution_state
// rides on recipe_created / recipe_updated payloads.
export type RecipeExecutionState = 'idle' | 'running' | 'paused'
export type RecipeStatusSummary = Record<string, number>
const counts = reactive<Record<number, number>>({})
const states = reactive<Record<number, RecipeExecutionState>>({})
// Root phase status_summary per recipe — written by useRecipeState whenever
// the active recipe's phase tree reloads. Read by useRecipeStatus so the
// sidebar's status label/dot match the RecipeView header.
const summaries = reactive<Record<number, RecipeStatusSummary>>({})
// Per-recipe program load_error flag — true when the program failed to
// build / dry-run preflight, so the status pill flips to Error even when
// the cached graph still has equations parked in awaiting_input. Sourced
// from the backend's recipe payload + recipe_updated broadcasts.
const loadErrors = reactive<Record<number, boolean>>({})
let refCount = 0
const unsubs: Array<() => void> = []
let primed = false

function setCount(recipeId: number | undefined | null, value: number | undefined | null) {
  if (typeof recipeId !== 'number') return
  counts[recipeId] = Math.max(0, value ?? 0)
}

function setState(recipeId: number | undefined | null, value: string | undefined | null) {
  if (typeof recipeId !== 'number') return
  if (value === 'running' || value === 'paused' || value === 'idle') {
    states[recipeId] = value
  }
}

function toNumericId(recipeId: number | string | null | undefined): number | null {
  if (recipeId === null || recipeId === undefined) return null
  const id = typeof recipeId === 'string' ? Number(recipeId) : recipeId
  return Number.isFinite(id) ? id : null
}

export function setRecipeStatusSummary(
  recipeId: number | string | null | undefined,
  summary: RecipeStatusSummary | null | undefined,
) {
  const id = toNumericId(recipeId)
  if (id === null) return
  if (summary == null) {
    delete summaries[id]
  } else {
    summaries[id] = { ...summary }
  }
}

export function setRecipeHasLoadError(
  recipeId: number | string | null | undefined,
  hasError: boolean,
) {
  const id = toNumericId(recipeId)
  if (id === null) return
  if (hasError) {
    loadErrors[id] = true
  } else {
    delete loadErrors[id]
  }
}

export function useRecipeCounts() {
  const api = useRecipesApi()
  const { on } = useWebSocket()

  async function prime() {
    if (primed) return
    primed = true
    try {
      const all = await api.listRecipes()
      for (const r of all) {
        setCount(r.id, r.pending_task_count ?? 0)
        setState(r.id, r.execution_state)
        if (r.root_status_summary) {
          setRecipeStatusSummary(r.id, r.root_status_summary)
        }
        setRecipeHasLoadError(r.id, !!r.has_load_error)
      }
    } catch {
      primed = false  // allow retry on next mount
    }
  }

  function countFor(recipeId: number | string | null | undefined): number {
    if (recipeId === null || recipeId === undefined) return 0
    const id = typeof recipeId === 'string' ? Number(recipeId) : recipeId
    return counts[id] ?? 0
  }

  function stateFor(recipeId: number | string | null | undefined): RecipeExecutionState {
    if (recipeId === null || recipeId === undefined) return 'idle'
    const id = typeof recipeId === 'string' ? Number(recipeId) : recipeId
    return states[id] ?? 'idle'
  }

  function summaryFor(recipeId: number | string | null | undefined): RecipeStatusSummary | undefined {
    const id = toNumericId(recipeId)
    if (id === null) return undefined
    return summaries[id]
  }

  function hasLoadErrorFor(recipeId: number | string | null | undefined): boolean {
    const id = toNumericId(recipeId)
    if (id === null) return false
    return loadErrors[id] === true
  }

  const totalPending = computed(() =>
    Object.values(counts).reduce((a, b) => a + b, 0)
  )

  function subscribe() {
    // WS events carry the fresh count so we don't need a refetch on every delta.
    unsubs.push(on('recipe_task_created', (data: any) => {
      if (typeof data?.pending_task_count === 'number') {
        setCount(data.recipe_id, data.pending_task_count)
      } else if (typeof data?.recipe_id === 'number') {
        counts[data.recipe_id] = (counts[data.recipe_id] ?? 0) + 1
      }
    }))
    unsubs.push(on('recipe_task_resolved', (data: any) => {
      if (typeof data?.pending_task_count === 'number') {
        setCount(data.recipe_id, data.pending_task_count)
      } else if (typeof data?.recipe_id === 'number') {
        counts[data.recipe_id] = Math.max(0, (counts[data.recipe_id] ?? 0) - 1)
      }
    }))
    unsubs.push(on('recipe_created', (data: any) => {
      const r = data?.recipe
      if (r?.id !== undefined) {
        setCount(r.id, r.pending_task_count ?? 0)
        setState(r.id, r.execution_state)
        if (r.root_status_summary) {
          setRecipeStatusSummary(r.id, r.root_status_summary)
        }
        setRecipeHasLoadError(r.id, !!r.has_load_error)
      }
    }))
    unsubs.push(on('recipe_updated', (data: any) => {
      const r = data?.recipe
      // Some `recipe_updated` payloads carry only { recipe_id, load_error }
      // (e.g. runtime broadcasting a build failure mid-reload). Honor those
      // by promoting the top-level load_error into the singleton even when
      // there's no recipe blob to read has_load_error from.
      const topLevelId = data?.recipe_id ?? r?.id
      if (typeof topLevelId === 'number') {
        if (Object.prototype.hasOwnProperty.call(data ?? {}, 'load_error')) {
          setRecipeHasLoadError(topLevelId, !!data.load_error)
        } else if (r && typeof r.has_load_error === 'boolean') {
          setRecipeHasLoadError(topLevelId, r.has_load_error)
        }
      }
      if (r?.id === undefined) return
      if (typeof r.pending_task_count === 'number') setCount(r.id, r.pending_task_count)
      setState(r.id, r.execution_state)
      if (r.root_status_summary) {
        setRecipeStatusSummary(r.id, r.root_status_summary)
      }
    }))
    // Equation transitions carry the fresh root status_summary so non-active
    // surfaces (sidebar, recipes landing, project overview) keep their pill
    // in sync without having to open the recipe to rehydrate the summary.
    unsubs.push(on('recipe_equation_updated', (data: any) => {
      if (data?.recipe_id != null && data.root_status_summary) {
        setRecipeStatusSummary(data.recipe_id, data.root_status_summary)
      }
    }))
    unsubs.push(on('recipe_deleted', (data: any) => {
      if (typeof data?.recipe_id === 'number') {
        delete counts[data.recipe_id]
        delete states[data.recipe_id]
        delete summaries[data.recipe_id]
        delete loadErrors[data.recipe_id]
      }
    }))
    // A full reconnect may have dropped deltas; re-prime from the source.
    unsubs.push(on('websocket_reconnected', () => {
      primed = false
      prime()
    }))
  }

  onMounted(() => {
    if (refCount === 0) {
      subscribe()
      prime()
    }
    refCount++
  })

  onUnmounted(() => {
    refCount = Math.max(0, refCount - 1)
    if (refCount === 0) {
      for (const u of unsubs) { try { u() } catch {} }
      unsubs.length = 0
      primed = false
    }
  })

  return { counts, countFor, stateFor, summaryFor, hasLoadErrorFor, totalPending }
}
