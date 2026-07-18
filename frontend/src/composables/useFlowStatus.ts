import { computed, type Ref } from 'vue'
import { useFlowCounts, type FlowExecutionState, type FlowStatusSummary } from './useFlowCounts'
import { dotClass, mapFlowStatus } from '../utils/statusColors'

/**
 * Shared status derivation for a flow — keeps the FlowView header and
 * NavigationSidebar in lockstep. Reads execution_state + the cached root
 * phase status_summary from the singleton (populated by useFlowState
 * whenever the active flow's phase tree reloads).
 *
 * Vocabulary: Idle / Paused / Running / Your Turn / Error / Done.
 * Equations also borrow this vocabulary (with `Waiting` for the
 * upstream-blocked case that doesn't apply at the workflow level).
 */
export type FlowStatusLabel =
  | 'Idle'
  | 'Paused'
  | 'Running'
  | 'Your Turn'
  | 'Waiting'
  | 'Error'
  | 'Done'

// Workflow priority: Error (load_error) > Paused > Error (failed eq) > Your Turn > Waiting > Running > Done > Idle.
// A program load_error trumps everything: the flow can't progress until
// the build is fixed, regardless of execution_state or what equations from
// a stale graph happen to be parked in awaiting_input. `Done` only applies
// once the runtime has actually reported zero pending / computing /
// awaiting / failed / waiting_for_tool; without a summary we still show
// `Running`. `Waiting` surfaces equations parked on a missing tool —
// self-heals when the tool comes online, no user action needed.
export function deriveFlowStatusLabel(
  execState: FlowExecutionState,
  sum: FlowStatusSummary | undefined,
  hasLoadError: boolean = false,
): FlowStatusLabel {
  if (hasLoadError) return 'Error'
  if (execState === 'paused') return 'Paused'
  if (execState === 'idle') return 'Idle'
  if (!sum) return 'Running'
  const computing = sum['computing'] || 0
  const pending   = sum['pending']   || 0
  const awaiting  = sum['awaiting_input'] || 0
  const waiting   = sum['waiting_for_tool'] || 0
  const failed    = sum['failed']    || 0
  if (failed > 0)   return 'Error'
  if (awaiting > 0) return 'Your Turn'
  if (computing > 0 || pending > 0) return 'Running'
  if (waiting > 0)  return 'Waiting'
  return 'Done'
}

// Colors route through the statusColors.ts single source of truth
// (STANDARDS.md §1.9). Running and Your Turn are the two "live" states —
// they get pulse-soft (never stock animate-pulse) on top of the bucket dot.
export function flowStatusDotClass(label: FlowStatusLabel): string {
  const base = dotClass(mapFlowStatus(label))
  const pulse = label === 'Running' || label === 'Your Turn' ? ' animate-pulse-soft' : ''
  return base + pulse
}

export function useFlowStatus(flowId: Ref<number | string | null | undefined>) {
  const { stateFor, summaryFor, hasLoadErrorFor } = useFlowCounts()

  const label = computed<FlowStatusLabel>(() =>
    deriveFlowStatusLabel(
      stateFor(flowId.value),
      summaryFor(flowId.value),
      hasLoadErrorFor(flowId.value),
    ),
  )

  const dotClass = computed<string>(() => flowStatusDotClass(label.value))

  return { label, dotClass }
}
