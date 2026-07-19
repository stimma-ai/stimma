export type FlowStatusLabel =
  | 'Idle'
  | 'Paused'
  | 'Running'
  | 'Your Turn'
  | 'Tool unavailable'
  | 'Error'
  | 'Done'

type FlowExecutionState = 'idle' | 'running' | 'paused'
type FlowStatusSummary = Record<string, number>

// Workflow priority: Error (load_error) > Paused > Error (failed eq) >
// Your Turn > Tool unavailable > Running > Done > Idle.
// A parked tool is distinct from ordinary pending work because it may
// require the person to reconnect a provider or log in to Stimma Cloud.
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
  const pending = sum['pending'] || 0
  const awaiting = sum['awaiting_input'] || 0
  const waiting = sum['waiting_for_tool'] || 0
  const failed = sum['failed'] || 0
  if (failed > 0) return 'Error'
  if (awaiting > 0) return 'Your Turn'
  if (waiting > 0) return 'Tool unavailable'
  if (computing > 0 || pending > 0) return 'Running'
  return 'Done'
}
