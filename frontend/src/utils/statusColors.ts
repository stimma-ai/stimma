// Atelier status colors — the single status→color source of truth
// (STANDARDS.md §1.9). Every surface that shows a status (flow status, job
// progress, pipeline segments, phase nodes, foreach counts, tab dots) must
// consume this map instead of inlining its own status→color switch.
//
// Buckets:
//   queued          zinc     not started yet / idle
//   running         blue     actively working
//   special         purple   llm/agent steps (enhancing, thinking, etc.)
//   awaiting        teal     "your turn" — the accent: actionable, pulses
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
  awaiting: 'bg-accent',
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
  awaiting: 'text-accent-hi',
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
  awaiting: 'bg-accent/15',
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

// A pending GroupedIteration's blockReason (why it hasn't started) — a
// second dimension layered on top of 'pending' status in IterationCard /
// FlowIterationRow / SlotApproveRow. Mapped to the same bucket vocabulary so
// a pending row's tint still comes from one map: 'human' reads as the
// upstream HITL it's waiting on (awaiting/accent), 'error' as the upstream
// failure it's blocked behind (failed/red), 'tool' as the non-fatal
// provider wait (warning/amber), 'cap' as "ready, just waiting for a slot"
// (running/blue, dimmed), and plain upstream compute as the default queued
// (zinc).
export type BlockReason = 'human' | 'error' | 'tool' | 'cap' | 'compute' | null | undefined
export function mapBlockReason(reason: BlockReason): StatusBucket {
  switch (reason) {
    case 'human': return 'awaiting'
    case 'error': return 'failed'
    case 'tool':  return 'warning'
    case 'cap':   return 'running'
    default:      return 'queued'
  }
}

// Card/row border+ring frame for iteration tiles and rows (IterationCard,
// FlowIterationRow, SlotApproveRow) — grandfathered as the media-tile
// exception to the depth-budget rule (STANDARDS §3.1 follow-up), so the
// card structure and opacity levels stay; only the bucket→color mapping is
// centralized here. `dimmed` is for a pending row whose blockReason echoes
// an upstream bucket at reduced opacity (nothing to act on yet).
const CARD_FRAME_STRONG: Record<StatusBucket, string> = {
  queued:   'border-edge-subtle hover:border-content-muted/60',
  running:  'border-blue-500/40',
  special:  'border-purple-500/50 ring-1 ring-purple-500/30',
  awaiting: 'border-accent/50 ring-1 ring-accent/30',
  done:     'border-edge-subtle hover:border-content-muted/60',
  failed:   'border-red-500/50',
  warning:  'border-amber-500/30 hover:border-amber-500/45',
  paused:   'border-amber-500/30 hover:border-amber-500/45',
  skipped:  'border-edge-subtle hover:border-content-muted/60',
}
const CARD_FRAME_DIMMED: Record<StatusBucket, string> = {
  queued:   'border-edge-subtle hover:border-content-muted/60',
  running:  'border-blue-500/25 hover:border-blue-500/40',
  special:  'border-purple-500/25 hover:border-purple-500/40',
  awaiting: 'border-accent/25 hover:border-accent/40',
  done:     'border-edge-subtle hover:border-content-muted/60',
  failed:   'border-red-500/25 hover:border-red-500/40',
  warning:  'border-amber-500/30 hover:border-amber-500/45',
  paused:   'border-amber-500/30 hover:border-amber-500/45',
  skipped:  'border-edge-subtle hover:border-content-muted/60',
}
export function cardFrameClass(bucket: StatusBucket, dimmed = false): string {
  return dimmed ? CARD_FRAME_DIMMED[bucket] : CARD_FRAME_STRONG[bucket]
}

// Tile placeholder background (IterationCard's no-media state) — /10 for
// the row's own state, a faint /[0.06] for a dimmed pending tile.
const TILE_BG_STRONG: Record<StatusBucket, string> = {
  queued: 'bg-overlay-faint', running: 'bg-overlay-faint', special: 'bg-purple-500/10',
  awaiting: 'bg-accent/10', done: 'bg-overlay-faint', failed: 'bg-red-500/10',
  warning: 'bg-overlay-faint', paused: 'bg-overlay-faint', skipped: 'bg-overlay-faint',
}
const TILE_BG_DIMMED: Record<StatusBucket, string> = {
  queued: 'bg-overlay-faint', running: 'bg-blue-500/[0.06]', special: 'bg-purple-500/[0.06]',
  awaiting: 'bg-accent/[0.06]', done: 'bg-overlay-faint', failed: 'bg-red-500/[0.06]',
  warning: 'bg-amber-500/[0.06]', paused: 'bg-amber-500/[0.06]', skipped: 'bg-overlay-faint',
}
export function tileBgClass(bucket: StatusBucket, dimmed = false): string {
  return dimmed ? TILE_BG_DIMMED[bucket] : TILE_BG_STRONG[bucket]
}

// Row wash background (FlowIterationRow's full-width body, SlotApproveRow's
// frame) — /5 for the row's own state, a faint /[0.04] for a dimmed
// pending row.
const ROW_BG_STRONG: Record<StatusBucket, string> = {
  queued: '', running: 'bg-blue-500/5', special: 'bg-purple-500/5', awaiting: 'bg-accent/5',
  done: '', failed: 'bg-red-500/5', warning: 'bg-amber-500/5', paused: 'bg-amber-500/5', skipped: '',
}
const ROW_BG_DIMMED: Record<StatusBucket, string> = {
  queued: '', running: 'bg-blue-500/[0.04]', special: 'bg-purple-500/[0.04]', awaiting: 'bg-accent/[0.04]',
  done: '', failed: 'bg-red-500/[0.04]', warning: 'bg-amber-500/[0.04]', paused: 'bg-amber-500/[0.04]', skipped: '',
}
export function rowBgClass(bucket: StatusBucket, dimmed = false): string {
  return dimmed ? ROW_BG_DIMMED[bucket] : ROW_BG_STRONG[bucket]
}

// Flow status vocabulary, as derived by useFlowStatus.ts's
// deriveFlowStatusLabel: Idle / Paused / Running / Your Turn /
// Tool unavailable / Error / Done. Tool unavailability is non-fatal and
// self-heals, so it maps to warning rather than awaiting.
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
    case 'Tool unavailable':
      return 'warning'
    case 'Error':
      return 'failed'
    case 'Done':
      return 'done'
    default:
      return 'queued'
  }
}
