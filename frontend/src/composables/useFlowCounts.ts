import { reactive, computed, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from './useWebSocket'
import { useFlowsApi } from './useFlowsApi'

// Singleton: pending task count + execution_state per flow id. Read by
// sidebar tab badges and landing-view FlowCards so every surface agrees
// without opening per-flow state.db. The counter is maintained
// server-side (flows.pending_task_count, denormalized) and flows in via
// flow_task_created / flow_task_resolved payloads; the execution_state
// rides on flow_created / flow_updated payloads.
export type FlowExecutionState = 'idle' | 'running' | 'paused'
export type FlowStatusSummary = Record<string, number>
const counts = reactive<Record<number, number>>({})
const states = reactive<Record<number, FlowExecutionState>>({})
// Root phase status_summary per flow — written by useFlowState whenever
// the active flow's phase tree reloads. Read by useFlowStatus so the
// sidebar's status label/dot match the FlowView header.
const summaries = reactive<Record<number, FlowStatusSummary>>({})
// Per-flow program load_error flag — true when the program failed to
// build / dry-run preflight, so the status pill flips to Error even when
// the cached graph still has equations parked in awaiting_input. Sourced
// from the backend's flow payload + flow_updated broadcasts.
const loadErrors = reactive<Record<number, boolean>>({})
let refCount = 0
const unsubs: Array<() => void> = []
let primed = false

function setCount(flowId: number | undefined | null, value: number | undefined | null) {
  if (typeof flowId !== 'number') return
  counts[flowId] = Math.max(0, value ?? 0)
}

function setState(flowId: number | undefined | null, value: string | undefined | null) {
  if (typeof flowId !== 'number') return
  if (value === 'running' || value === 'paused' || value === 'idle') {
    states[flowId] = value
  }
}

function toNumericId(flowId: number | string | null | undefined): number | null {
  if (flowId === null || flowId === undefined) return null
  const id = typeof flowId === 'string' ? Number(flowId) : flowId
  return Number.isFinite(id) ? id : null
}

export function setFlowStatusSummary(
  flowId: number | string | null | undefined,
  summary: FlowStatusSummary | null | undefined,
) {
  const id = toNumericId(flowId)
  if (id === null) return
  if (summary == null) {
    delete summaries[id]
  } else {
    summaries[id] = { ...summary }
  }
}

export function setFlowHasLoadError(
  flowId: number | string | null | undefined,
  hasError: boolean,
) {
  const id = toNumericId(flowId)
  if (id === null) return
  if (hasError) {
    loadErrors[id] = true
  } else {
    delete loadErrors[id]
  }
}

export function useFlowCounts() {
  const api = useFlowsApi()
  const { on } = useWebSocket()

  async function prime() {
    if (primed) return
    primed = true
    try {
      const all = await api.listFlows()
      for (const r of all) {
        setCount(r.id, r.pending_task_count ?? 0)
        setState(r.id, r.execution_state)
        if (r.root_status_summary) {
          setFlowStatusSummary(r.id, r.root_status_summary)
        }
        setFlowHasLoadError(r.id, !!r.has_load_error)
      }
    } catch {
      primed = false  // allow retry on next mount
    }
  }

  function countFor(flowId: number | string | null | undefined): number {
    if (flowId === null || flowId === undefined) return 0
    const id = typeof flowId === 'string' ? Number(flowId) : flowId
    return counts[id] ?? 0
  }

  function stateFor(flowId: number | string | null | undefined): FlowExecutionState {
    if (flowId === null || flowId === undefined) return 'idle'
    const id = typeof flowId === 'string' ? Number(flowId) : flowId
    return states[id] ?? 'idle'
  }

  function summaryFor(flowId: number | string | null | undefined): FlowStatusSummary | undefined {
    const id = toNumericId(flowId)
    if (id === null) return undefined
    return summaries[id]
  }

  function hasLoadErrorFor(flowId: number | string | null | undefined): boolean {
    const id = toNumericId(flowId)
    if (id === null) return false
    return loadErrors[id] === true
  }

  const totalPending = computed(() =>
    Object.values(counts).reduce((a, b) => a + b, 0)
  )

  function subscribe() {
    // WS events carry the fresh count so we don't need a refetch on every delta.
    unsubs.push(on('flow_task_created', (data: any) => {
      if (typeof data?.pending_task_count === 'number') {
        setCount(data.flow_id, data.pending_task_count)
      } else if (typeof data?.flow_id === 'number') {
        counts[data.flow_id] = (counts[data.flow_id] ?? 0) + 1
      }
    }))
    unsubs.push(on('flow_task_resolved', (data: any) => {
      if (typeof data?.pending_task_count === 'number') {
        setCount(data.flow_id, data.pending_task_count)
      } else if (typeof data?.flow_id === 'number') {
        counts[data.flow_id] = Math.max(0, (counts[data.flow_id] ?? 0) - 1)
      }
    }))
    unsubs.push(on('flow_created', (data: any) => {
      const r = data?.flow
      if (r?.id !== undefined) {
        setCount(r.id, r.pending_task_count ?? 0)
        setState(r.id, r.execution_state)
        if (r.root_status_summary) {
          setFlowStatusSummary(r.id, r.root_status_summary)
        }
        setFlowHasLoadError(r.id, !!r.has_load_error)
      }
    }))
    unsubs.push(on('flow_updated', (data: any) => {
      const r = data?.flow
      // Some `flow_updated` payloads carry only { flow_id, load_error }
      // (e.g. runtime broadcasting a build failure mid-reload). Honor those
      // by promoting the top-level load_error into the singleton even when
      // there's no flow blob to read has_load_error from.
      const topLevelId = data?.flow_id ?? r?.id
      if (typeof topLevelId === 'number') {
        if (Object.prototype.hasOwnProperty.call(data ?? {}, 'load_error')) {
          setFlowHasLoadError(topLevelId, !!data.load_error)
        } else if (r && typeof r.has_load_error === 'boolean') {
          setFlowHasLoadError(topLevelId, r.has_load_error)
        }
      }
      if (r?.id === undefined) return
      if (typeof r.pending_task_count === 'number') setCount(r.id, r.pending_task_count)
      setState(r.id, r.execution_state)
      if (r.root_status_summary) {
        setFlowStatusSummary(r.id, r.root_status_summary)
      }
    }))
    // Equation transitions carry the fresh root status_summary so non-active
    // surfaces (sidebar, flows landing, project overview) keep their pill
    // in sync without having to open the flow to rehydrate the summary.
    unsubs.push(on('flow_equation_updated', (data: any) => {
      if (data?.flow_id != null && data.root_status_summary) {
        setFlowStatusSummary(data.flow_id, data.root_status_summary)
      }
    }))
    unsubs.push(on('flow_deleted', (data: any) => {
      if (typeof data?.flow_id === 'number') {
        delete counts[data.flow_id]
        delete states[data.flow_id]
        delete summaries[data.flow_id]
        delete loadErrors[data.flow_id]
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
