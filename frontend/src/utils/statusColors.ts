// Atelier status colors — the single status→color source of truth
// (STANDARDS.md §1.9). Every surface that shows a status (flow status, job
// progress, pipeline segments, phase nodes, foreach counts, tab dots) must
// consume this map instead of inlining its own status→color switch.
//
// Buckets:
//   queued          zinc     not started yet / idle
//   running         blue     actively working
//   special         purple   llm/agent steps (enhancing, thinking, etc.)
//   awaiting        purple   "your turn" — same family as special, pulses
//   done            green    terminal success
//   failed          red      terminal failure
//   warning         amber    non-fatal trouble (timed out, partial, waiting)
//   paused          amber    same family as warning — user/system paused
//   skipped         zinc     terminal, intentionally not run — dimmed

export type StatusBucket =
  | 'queued'
  | 'running'
  | 'special'
  | 'awaiting'
  | 'done'
  | 'failed'
  | 'warning'
  | 'paused'
  | 'skipped'

const DOT_CLASS: Record<StatusBucket, string> = {
  queued: 'bg-zinc-500',
  running: 'bg-blue-500',
  special: 'bg-purple-500',
  awaiting: 'bg-purple-500',
  done: 'bg-green-500',
  failed: 'bg-red-500',
  warning: 'bg-amber-500',
  paused: 'bg-amber-500',
  skipped: 'bg-zinc-500/50',
}

const TEXT_CLASS: Record<StatusBucket, string> = {
  queued: 'text-content-muted',
  running: 'text-blue-400',
  special: 'text-purple-400',
  awaiting: 'text-purple-400',
  done: 'text-green-400',
  failed: 'text-red-400',
  warning: 'text-amber-400',
  paused: 'text-amber-400',
  skipped: 'text-content-muted',
}

const BG_CLASS: Record<StatusBucket, string> = {
  queued: 'bg-zinc-500/15',
  running: 'bg-blue-500/15',
  special: 'bg-purple-500/15',
  awaiting: 'bg-purple-500/15',
  done: 'bg-green-500/15',
  failed: 'bg-red-500/15',
  warning: 'bg-amber-500/15',
  paused: 'bg-amber-500/15',
  skipped: 'bg-zinc-500/10',
}

export function dotClass(bucket: StatusBucket): string {
  return DOT_CLASS[bucket]
}

export function textClass(bucket: StatusBucket): string {
  return TEXT_CLASS[bucket]
}

export function bgClass(bucket: StatusBucket): string {
  return BG_CLASS[bucket]
}

// Job status vocabulary, as used by useGenerationJobs.js (jobs: queued,
// assigned, processing, completed, failed, cancelled — plus batch statuses
// completed/partial/failed, and the postprocessing 'enhancing'/'in_progress'/
// 'timed_out'/'cancelled' states from ProgressDisplay.vue's displayData.status).
export function mapJobStatus(s: string): StatusBucket {
  switch (s) {
    case 'queued':
    case 'assigned':
      return 'queued'
    case 'processing':
    case 'in_progress':
      return 'running'
    case 'enhancing':
      return 'special'
    case 'completed':
      return 'done'
    case 'failed':
    case 'error':
      return 'failed'
    case 'paused':
      return 'paused'
    case 'partial':
    case 'timed_out':
      return 'warning'
    case 'cancelled':
    case 'skipped':
      return 'skipped'
    default:
      return 'queued'
  }
}

// Equation status vocabulary (FlowEquation.status), shared by the flow
// panel components (PhaseNode, EquationTraceRow, IterationGroup,
// GraphInspectPanel, TaskCard) so a step's status color is derived in one
// place instead of five duplicated switches. 'invalidated' (stale, needs
// re-run) and 'waiting_for_tool' both read as non-fatal trouble → warning
// (amber); 'pending' reads as queued (zinc) regardless of whether it's
// ready-to-schedule or still blocked upstream — callers needing that
// distinction layer it on top (see isQueued in EquationTraceRow).
export function mapEquationStatus(status: string | null | undefined): StatusBucket {
  switch (status) {
    case 'completed':       return 'done'
    case 'computing':       return 'running'
    case 'failed':          return 'failed'
    case 'awaiting_input':  return 'awaiting'
    case 'waiting_for_tool':
    case 'invalidated':     return 'warning'
    case 'skipped':         return 'skipped'
    case 'pending':
    default:                return 'queued'
  }
}

// Flow status vocabulary, as derived by useFlowStatus.ts's
// deriveFlowStatusLabel: Idle / Paused / Running / Your Turn / Waiting /
// Error / Done. 'Waiting' is the upstream-blocked-on-a-missing-tool case —
// non-fatal, self-heals — so it maps to warning rather than awaiting.
export function mapFlowStatus(s: string): StatusBucket {
  switch (s) {
    case 'Idle':
      return 'queued'
    case 'Paused':
      return 'paused'
    case 'Running':
      return 'running'
    case 'Your Turn':
      return 'awaiting'
    case 'Waiting':
      return 'warning'
    case 'Error':
      return 'failed'
    case 'Done':
      return 'done'
    default:
      return 'queued'
  }
}
