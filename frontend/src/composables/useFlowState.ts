import { ref, onMounted, onUnmounted, watch, type Ref } from 'vue'
import { useWebSocket } from './useWebSocket'
import {
  useFlowsApi,
  type Flow,
  type FlowTask,
  type FlowEquation,
  type PhaseTree,
  type PhaseNode,
} from './useFlowsApi'
import { setFlowStatusSummary, setFlowHasLoadError } from './useFlowCounts'
import { addToast } from './useToasts'

/**
 * Per-flow reactive state. Loads flow + phase tree + tasks on mount,
 * subscribes to flow_* WebSocket events, exposes actions.
 */
export function useFlowState(flowId: Ref<number | string | null>) {
  const api = useFlowsApi()
  const { on } = useWebSocket()

  const flow = ref<Flow | null>(null)
  const phaseTree = ref<PhaseTree | null>(null)
  const equations = ref<FlowEquation[]>([])
  const equationsByKey = ref<Map<string, FlowEquation>>(new Map())
  const tasks = ref<FlowTask[]>([])
  const loading = ref(false)
  const loadError = ref<string | null>(null)
  const resolvingTaskIds = new Set<string>()
  // Program-load error from a rebuild attempt (e.g. the agent wrote a new
  // program.py but it references inputs the flow doesn't have values for
  // yet). Broadcast via flow_updated { load_error: ... } so the UI can
  // explain why the phase tree is empty without waiting for Start.
  const programLoadError = ref<{
    category: string
    message: string
    suggestion?: string | null
    program_traceback?: string | null
    issues?: Array<{
      equation_key: string
      equation_type: string
      status: string
      message: string
      category: string
      phase_path: string[]
    }> | null
  } | null>(null)

  const unsubs: Array<() => void> = []

  // Debounce helper: coalesces rapid WS events (e.g. N equation-updated events
  // from a single invalidation cascade) into one HTTP reload pair.
  let _reloadTimer: ReturnType<typeof setTimeout> | null = null
  function scheduleReload(includeEquations = true) {
    if (_reloadTimer) clearTimeout(_reloadTimer)
    _reloadTimer = setTimeout(() => {
      _reloadTimer = null
      loadPhaseTree()
      if (includeEquations) loadEquations()
    }, 120)
  }

  function equationsFromTree(root: PhaseNode): string[] {
    const out: string[] = [...root.equation_keys]
    for (const c of root.children) out.push(...equationsFromTree(c))
    return out
  }

  function rebuildEquationMap() {
    const map = new Map<string, FlowEquation>()
    for (const eq of equations.value) map.set(eq.equation_key, eq)
    equationsByKey.value = map
  }

  function sameJson(a: any, b: any): boolean {
    return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
  }

  async function loadFlow() {
    const id = flowId.value
    if (id == null) return
    try {
      flow.value = await api.getFlow(id)
    } catch (err: any) {
      loadError.value = err?.message || 'Failed to load flow'
    }
  }

  async function loadPhaseTree() {
    const id = flowId.value
    if (id == null) return
    try {
      phaseTree.value = await api.getPhaseTree(id)
      programLoadError.value = phaseTree.value?.load_error ?? null
      // Mirror the root status_summary into the shared singleton so the
      // sidebar's status label/dot stays in lockstep with the header.
      setFlowStatusSummary(id, phaseTree.value?.root?.status_summary ?? {})
      setFlowHasLoadError(id, !!phaseTree.value?.load_error)
    } catch (err: any) {
      loadError.value = err?.message || 'Failed to load phase tree'
    }
  }

  async function loadEquations() {
    const id = flowId.value
    if (id == null) return
    try {
      equations.value = await api.listEquations(id)
      rebuildEquationMap()
    } catch (err: any) {
      loadError.value = err?.message || 'Failed to load equations'
    }
  }

  async function loadTasks() {
    const id = flowId.value
    if (id == null) return
    try {
      const pendingTasks = await api.listFlowTasks(id, { status: 'pending' })
      tasks.value = pendingTasks.filter((task) => !resolvingTaskIds.has(task.task_id))
    } catch (err: any) {
      loadError.value = err?.message || 'Failed to load tasks'
    }
  }

  function removeTaskOptimistically(taskId: string): FlowTask | null {
    const idx = tasks.value.findIndex((task) => task.task_id === taskId)
    if (idx < 0) return null
    const [removed] = tasks.value.splice(idx, 1)
    return removed ?? null
  }

  function restoreTask(task: FlowTask | null) {
    if (!task) return
    if (tasks.value.some((existing) => existing.task_id === task.task_id)) return
    tasks.value = [...tasks.value, task].sort((a, b) => {
      const da = Date.parse(a.created_at || '')
      const db = Date.parse(b.created_at || '')
      if (Number.isFinite(da) && Number.isFinite(db) && da !== db) return da - db
      return a.task_id.localeCompare(b.task_id)
    })
  }

  async function loadAll() {
    const id = flowId.value
    if (id == null) return
    loading.value = true
    loadError.value = null
    try {
      await Promise.all([loadFlow(), loadPhaseTree(), loadEquations(), loadTasks()])
    } finally {
      loading.value = false
    }
  }

  function matchesCurrent(payloadFlowId: any): boolean {
    if (flowId.value == null) return false
    return String(payloadFlowId) === String(flowId.value)
  }

  // --- WebSocket subscriptions ---
  function subscribe() {
    unsubs.push(
      on('flow_updated', (data: any) => {
        const r = data?.flow
        const payloadFlowId = r?.id ?? data?.flow_id
        if (!matchesCurrent(payloadFlowId)) return
        const prev = flow.value
        const programChanged = r ? (!prev || prev.program_hash !== r.program_hash) : false
        const inputsChanged = r && prev ? !sameJson(prev.inputs, r.inputs) : false
        const schemaChanged = r && prev
          ? !sameJson(prev.input_schema, r.input_schema) || !sameJson(prev.output_schema, r.output_schema)
          : false
        if (r) flow.value = r
        if (data?.load_error) {
          programLoadError.value = data.load_error
        } else if (programChanged || data?.graph_diff) {
          programLoadError.value = null
        }
        if (programChanged || data?.graph_diff || data?.load_error || inputsChanged || schemaChanged) {
          // Graph-affecting flow update — full reload to pick up structure,
          // input-settling, task changes, and any cached load_error state.
          loadPhaseTree()
          loadEquations()
          loadTasks()
        }
      })
    )
    unsubs.push(
      on('flow_equation_updated', (data: any) => {
        if (!matchesCurrent(data?.flow_id)) return
        // Update the equation in-place from the WS payload (zero latency).
        const eq = equationsByKey.value.get(data.equation_key)
        if (eq) {
          eq.status = data.status
          if (data.result_media_ids != null) eq.result_media_ids = data.result_media_ids
          if (data.execution_duration_ms != null || data.execution_duration_ms === null) {
            eq.execution_duration_ms = data.execution_duration_ms
          }
          if (data.compute_duration_ms != null || data.compute_duration_ms === null) {
            eq.compute_duration_ms = data.compute_duration_ms
          }
          eq.error = data.error ?? undefined
          if (data.attempt != null) eq.attempt = data.attempt
        }
        // Debounce the full reload — collapses N cascade events into one call.
        scheduleReload()
      })
    )
    unsubs.push(
      on('flow_phase_updated', (data: any) => {
        if (!matchesCurrent(data?.flow_id)) return
        // Phase updates can accompany structural changes (e.g. foreach
        // iteration expansion) that add or reshape equations. Reload both.
        scheduleReload()
      })
    )
    unsubs.push(
      on('flow_task_created', (data: any) => {
        if (!matchesCurrent(data?.flow_id)) return
        loadTasks()
        scheduleReload(false)
      })
    )
    unsubs.push(
      on('flow_task_resolved', (data: any) => {
        if (!matchesCurrent(data?.flow_id)) return
        loadTasks()
        scheduleReload()
      })
    )
    unsubs.push(
      on('websocket_reconnected', () => {
        loadAll()
      })
    )
    unsubs.push(
      on('flow_deleted', (data: any) => {
        if (matchesCurrent(data?.flow_id)) {
          flow.value = null
        }
      })
    )
  }

  // --- Actions ---
  async function start() {
    if (flowId.value == null) return
    try {
      flow.value = await api.startFlow(flowId.value)
      programLoadError.value = null
      await loadAll()
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Start failed'
      programLoadError.value = { category: 'build_error', message: detail }
      throw err
    }
  }

  async function pause() {
    if (flowId.value == null) return
    flow.value = await api.pauseFlow(flowId.value)
  }

  async function resume() {
    if (flowId.value == null) return
    flow.value = await api.resumeFlow(flowId.value)
  }

  async function clear() {
    if (flowId.value == null) return
    flow.value = await api.clearFlow(flowId.value)
    programLoadError.value = null
    await loadAll()
  }

  async function reparse() {
    if (flowId.value == null) return
    flow.value = await api.reparseFlow(flowId.value)
    await loadAll()
  }

  async function fork(inputs: Record<string, any>, name?: string): Promise<Flow> {
    if (flowId.value == null) throw new Error('No flow loaded')
    return api.forkFlow(flowId.value, { inputs, name })
  }

  async function updateMetadata(body: Partial<Flow>): Promise<Flow> {
    if (flowId.value == null) throw new Error('No flow loaded')
    const r = await api.updateFlow(flowId.value, body)
    flow.value = r
    return r
  }

  async function invalidateEquation(equationKey: string) {
    if (flowId.value == null) return
    // Optimistic: flip the targeted equation to pending immediately so the
    // spinner appears before the WS event arrives.
    const eq = equationsByKey.value.get(equationKey)
    if (eq) {
      eq.status = 'pending'
      eq.result_media_ids = []
      eq.execution_duration_ms = null
      eq.compute_duration_ms = null
      eq.error = undefined
    }
    await api.invalidateEquation(flowId.value, equationKey)
    // WS events from the backend cascade will trigger the debounced reload.
  }

  async function invalidatePhase(phasePath: string[]) {
    if (flowId.value == null) return
    await api.invalidatePhase(flowId.value, phasePath)
    // WS events handle the reload.
  }

  async function reselectEquation(equationKey: string, resolution: any) {
    if (flowId.value == null) return
    // Optimistic: update the local equation's result so the UI reflects
    // the new pick before the WS event arrives. Downstream flips to
    // pending server-side; the WS cascade will sync those rows.
    const eq = equationsByKey.value.get(equationKey)
    if (eq) {
      eq.result = resolution
      const mids: number[] = []
      if (typeof resolution === 'number') mids.push(resolution)
      else if (Array.isArray(resolution)) {
        for (const x of resolution) if (typeof x === 'number') mids.push(x)
      }
      eq.result_media_ids = mids
    }
    await api.reselectEquation(flowId.value, equationKey, resolution)
  }

  async function resolveTask(taskId: string, resolution: any) {
    resolvingTaskIds.add(taskId)
    const removed = removeTaskOptimistically(taskId)
    try {
      await api.resolveTask(taskId, { resolution })
      await loadTasks()
      scheduleReload()
    } catch (err: any) {
      resolvingTaskIds.delete(taskId)
      restoreTask(removed)
      // Per-task failure (e.g. a hitl.select pick that 403s on download).
      // Surface as a toast and leave the rest of the flow view intact —
      // setting loadError here would render the whole steps list as a
      // "Stimma is unavailable" empty state, which is wildly out of
      // proportion with a single bad URL.
      const detail = err?.response?.data?.detail || err?.message || 'Failed to resolve task'
      addToast(detail, 'error', 8000)
      throw err
    } finally {
      resolvingTaskIds.delete(taskId)
    }
  }

  async function resolveErrorTask(taskId: string, action: string, value?: any) {
    resolvingTaskIds.add(taskId)
    const removed = removeTaskOptimistically(taskId)
    try {
      await api.resolveTask(taskId, { action, value })
      await loadTasks()
      scheduleReload()
    } catch (err: any) {
      resolvingTaskIds.delete(taskId)
      restoreTask(removed)
      const detail = err?.response?.data?.detail || err?.message || 'Failed to resolve task'
      addToast(detail, 'error', 8000)
      throw err
    } finally {
      resolvingTaskIds.delete(taskId)
    }
  }

  async function remove() {
    if (flowId.value == null) return
    await api.deleteFlow(flowId.value)
  }

  // Auto-load when flowId changes
  watch(flowId, () => { loadAll() }, { immediate: false })

  onMounted(() => {
    subscribe()
    loadAll()
  })

  onUnmounted(() => {
    if (_reloadTimer) {
      clearTimeout(_reloadTimer)
      _reloadTimer = null
    }
    for (const u of unsubs) {
      try { u() } catch {}
    }
    unsubs.length = 0
  })

  return {
    flow,
    phaseTree,
    equations,
    equationsByKey,
    tasks,
    loading,
    loadError,
    programLoadError,
    loadAll,
    loadFlow,
    loadPhaseTree,
    loadEquations,
    loadTasks,
    start,
    pause,
    resume,
    clear,
    reparse,
    fork,
    updateMetadata,
    invalidateEquation,
    reselectEquation,
    invalidatePhase,
    resolveTask,
    resolveErrorTask,
    remove,
  }
}
