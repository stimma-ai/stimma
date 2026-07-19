import { computed, type Ref } from 'vue'
import { useFlowCounts } from './useFlowCounts'
import { dotClass, mapFlowStatus } from '../utils/statusColors'
import { deriveFlowStatusLabel, type FlowStatusLabel } from '../utils/flowStatus'

export { deriveFlowStatusLabel, type FlowStatusLabel } from '../utils/flowStatus'

/**
 * Shared status derivation for a flow — keeps the FlowView header and
 * NavigationSidebar in lockstep. Reads execution_state + the cached root
 * phase status_summary from the singleton (populated by useFlowState
 * whenever the active flow's phase tree reloads).
 *
 * Vocabulary: Idle / Paused / Running / Your Turn / Tool unavailable /
 * Error / Done.
 */
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
