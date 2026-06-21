<template>
  <!-- A SlotCell is an HITL approval card from birth — its identity does
       not change with state. Visual chrome is intentionally quiet (one
       border treatment, no per-state frame tints) so the cell reads as
       a normal HITL surface; the actions in the footer are what change. -->
  <div
    class="rounded-md border overflow-hidden flex flex-col"
    :class="frameClass"
  >
    <div class="relative aspect-square w-full bg-overlay-faint">
      <FlowMediaTile
        v-if="primaryMediaId"
        :media-id="primaryMediaId"
        :media-ids="primaryMediaIds"
        :thumbnail="true"
        :thumbnail-size="256"
        :contain="true"
        container-class="w-full h-full"
      />
      <div
        v-else
        class="absolute inset-0 flex items-center justify-center"
      >
        <span
          v-if="cellState === 'generating' || cellState === 'regenerating'"
          class="w-5 h-5 border-2 border-content-muted/60 border-t-transparent rounded-full animate-spin"
        />
        <svg
          v-else-if="cellState === 'failed'"
          class="w-6 h-6 text-red-400"
          fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span
          v-else
          class="text-[11px] text-content-muted"
        >Slot {{ slotIndex }}</span>
      </div>

      <!-- Regenerating: tinted veil + spinner badge. Communicates motion
           on a cell that's about to turn over without recoloring the cell
           frame itself. -->
      <div
        v-if="cellState === 'regenerating' && primaryMediaId"
        class="absolute inset-0 bg-black/40 flex items-center justify-center"
      >
        <div class="flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[10.5px] font-medium text-white">
          <span class="w-3 h-3 border-2 border-white/80 border-t-transparent rounded-full animate-spin" />
          Regenerating
        </div>
      </div>

      <div
        v-if="durationLabel"
        class="absolute bottom-1 left-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white tabular-nums"
      >{{ durationLabel }}</div>
    </div>

    <!-- Footer. Always present so the cell layout is stable. The UI uses
         Approve / Replace language here because hitl.approve is a curation
         surface: rejecting a slot means "make me a different one". -->
    <div
      class="border-t border-edge-subtle bg-overlay-faint flex items-center px-2 py-1.5 min-h-[34px] gap-2"
    >
      <!-- Approved collapses to one full-width toggle. Clicking it clears
           approval and returns to the two-action Approve / Replace state. -->
      <template v-if="cellState === 'approved'">
        <button
          type="button"
          aria-pressed="true"
          class="flex-1 bg-blue-500 text-white border border-blue-500 text-[11px] font-medium px-2.5 py-1 rounded hover:bg-blue-600 transition-colors"
          title="Click to unapprove"
          @click.stop="unapprove()"
        >Approved</button>
      </template>

      <template v-else-if="cellState === 'awaiting'">
        <button
          type="button"
          aria-pressed="false"
          class="bg-blue-500/15 border border-blue-500/50 text-blue-400 text-[11px] font-medium px-2.5 py-1 rounded hover:bg-blue-500/25 transition-colors"
          title="Approve (↑)"
          @click.stop="submitApprove(true)"
        >Approve</button>
        <button
          type="button"
          class="bg-overlay-subtle border border-edge-subtle text-content-secondary text-[11px] font-medium px-2.5 py-1 rounded hover:bg-overlay-hover hover:text-content transition-colors"
          title="Replace — regenerates this slot (↓)"
          @click.stop="submitApprove(false)"
        >Replace</button>
      </template>

      <!-- Status-only states: muted text, no buttons. -->
      <span
        v-else-if="cellState === 'generating'"
        class="text-[11px] text-content-muted"
      >Generating…</span>
      <span
        v-else-if="cellState === 'regenerating'"
        class="text-[11px] text-content-muted"
      >Regenerating…</span>
      <span
        v-else-if="cellState === 'pending'"
        class="text-[11px] text-content-muted"
      >Queued</span>

      <!-- Failed: retry button using the same neutral treatment as
           "Redo" on completed HITL rows in PhaseNode. -->
      <button
        v-else-if="cellState === 'failed'"
        type="button"
        class="text-[11px] px-2 py-0.5 rounded bg-overlay-subtle border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-hover transition-colors"
        @click.stop="$emit('invalidate', invalidateKey)"
      >Retry ↻</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import FlowMediaTile from './FlowMediaTile.vue'
import type { GroupedIteration } from '../../composables/useFlowGrouping'
import type { FlowTask } from '../../composables/useFlowsApi'
import { shouldShowEquationDuration } from '../../utils/equationDuration'

interface Props {
  slot: GroupedIteration
  slotIndex: number
  // Tasks indexed by equation_key. The cell looks up its own pending
  // approve task here; SlotGroup is responsible for passing the same
  // map every render.
  tasksByEquationKey: Map<string, FlowTask[]>
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'resolve-task', task: FlowTask, resolution: any): void
  (e: 'invalidate', equationKey: string): void
}>()

// Pending approve task for this slot. We walk the slot's equations
// looking for a HITL approve whose task is pending. The auto-injected
// approve is always the slot's terminal equation, so if any pending
// approve exists, it's the one for this slot.
const pendingApproveTask = computed<FlowTask | null>(() => {
  for (const eq of props.slot.equations) {
    if (eq.equation_type !== 'hitl') continue
    const tasks = props.tasksByEquationKey.get(eq.equation_key)
    if (!tasks) continue
    for (const t of tasks) {
      if (t.task_type === 'approve' && t.status === 'pending') return t
    }
  }
  return null
})

// The slot's approve equation, regardless of pending state. Used to
// distinguish "approved" (completed approve with truthy result) from
// "regenerating" (approve was rejected and is now pending again).
const approveEquation = computed(() => {
  for (const eq of props.slot.equations) {
    if (eq.equation_type === 'hitl' && eq.hitl_kind === 'approve') return eq
  }
  return null
})
const approveEquationKey = computed<string | null>(
  () => approveEquation.value?.equation_key ?? null,
)

const candidateProducer = computed(() => {
  return props.slot.equations.find(
    (e) => e.equation_type !== 'hitl'
      && e.result_media_ids
      && e.result_media_ids.length > 0,
  ) ?? props.slot.primary ?? null
})

// Cell state. Mutually exclusive — every render lands in exactly one.
type CellState =
  | 'awaiting'        // pending approve task, ready to act
  | 'approved'        // approve completed with truthy result
  | 'generating'      // first-time generation, no media yet
  | 'regenerating'    // generator is re-running after a rejection
  | 'pending'         // queued, upstream not started
  | 'failed'          // generator or approve failed

const cellState = computed<CellState>(() => {
  if (props.slot.hasError) return 'failed'
  if (pendingApproveTask.value) return 'awaiting'
  if (approveEquation.value?.status === 'completed') {
    return approveEquation.value.result === false ? 'regenerating' : 'approved'
  }
  if (props.slot.status === 'computing') {
    return primaryMediaId.value ? 'regenerating' : 'generating'
  }
  return 'pending'
})

// The slot's primary media — the candidate-producing tool/llm/code.
const primaryMediaIds = computed<number[]>(() => {
  // Prefer the user's generator output (the inner tool call) over the
  // approve equation, which mirrors the same media but carries the
  // user's accept/reject signal as its result.
  if (candidateProducer.value?.result_media_ids) return candidateProducer.value.result_media_ids
  return props.slot.primary?.result_media_ids ?? []
})
const primaryMediaId = computed<number | null>(() => primaryMediaIds.value[0] ?? null)

const durationLabel = computed<string | null>(() => {
  // Pure compute time on the candidate producer when available, so
  // "this image took 6.0s" reflects model time, not queue + approve.
  const eq = props.slot.equations.find(
    (e) => shouldShowEquationDuration(e.equation_type) && e.status === 'completed',
  )
  if (!eq) return null
  const ms = typeof eq.compute_duration_ms === 'number' && eq.compute_duration_ms >= 0
    ? eq.compute_duration_ms
    : eq.execution_duration_ms
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

// Keep the card frame neutral. The footer controls carry the decision
// state; duplicating that state in the frame makes the grid hard to read.
const frameClass = computed(() => {
  switch (cellState.value) {
    case 'failed':   return 'border-red-500/50'
    default:         return 'border-edge-subtle'
  }
})

const invalidateKey = computed<string | null>(() => {
  // For retry on failure, prefer the failed equation; fall back to the
  // primary candidate producer.
  const failed = props.slot.equations.find((e) => e.status === 'failed')
  if (failed) return failed.equation_key
  return props.slot.primary?.equation_key ?? props.slot.wrapperKey ?? null
})

function submitApprove(approved: boolean) {
  const t = pendingApproveTask.value
  if (!t) return
  emit('resolve-task', t, approved)
}

function unapprove() {
  if (!approveEquationKey.value) return
  emit('invalidate', approveEquationKey.value)
}
</script>
