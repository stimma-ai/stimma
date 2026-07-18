<template>
  <!-- Row variant of SlotApproveCell. Same state machine — read the
       approve equation status + pending task list, resolve the
       candidate producer to find what the user is actually approving
       — but lays out as a full-width row so the candidate's text
       (LLM prompts, JSON, etc.) reads at full size with the
       Approve/Replace controls pinned to the right. The square-tile
       SlotApproveCell stays for media candidates. -->
  <div
    class="rounded-md border overflow-hidden flex items-stretch transition-colors"
    :class="frameClass"
  >
    <div class="flex-shrink-0 w-7 flex items-start justify-center pt-2 border-r border-edge-subtle">
      <span
        v-if="cellState === 'awaiting'"
        class="w-2 h-2 mt-1 rounded-full bg-purple-400"
      />
      <svg
        v-else-if="cellState === 'approved'"
        class="w-4 h-4 text-green-500"
        fill="currentColor" viewBox="0 0 24 24"
      >
        <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
      </svg>
      <svg
        v-else-if="cellState === 'failed'"
        class="w-4 h-4 text-red-400"
        fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      <span
        v-else
        class="w-3 h-3 mt-1 border-2 border-content-muted/60 border-t-transparent rounded-full animate-spin"
      />
    </div>

    <div class="flex-1 min-w-0 px-3 py-2">
      <FlowResultPreview
        v-if="hasContent"
        :value="candidateProducer?.result"
      />
      <div v-else class="text-[12px] text-content-muted">
        {{ cellState === 'failed' ? 'Failed to generate' : 'Generating…' }}
      </div>
    </div>

    <!-- Right-pinned action footer. Mirrors HitlActionCard's button
         vocabulary so a flow with mixed media-grid + text-row
         approvals reads as the same widget shape. -->
    <div class="flex-shrink-0 flex flex-col items-stretch justify-center gap-1 p-2 border-l border-edge-subtle bg-overlay-faint w-[120px]">
      <template v-if="cellState === 'awaiting'">
        <button
          type="button"
          class="bg-accent text-white text-[11px] font-medium px-2 py-1 rounded-md hover:bg-accent/90 transition-colors"
          @click.stop="submitApprove(true)"
        >Approve</button>
        <button
          type="button"
          class="bg-overlay-subtle text-content-secondary text-[11px] font-medium px-2 py-1 rounded-md hover:bg-overlay-hover hover:text-content transition-colors"
          title="Regenerate this slot"
          @click.stop="submitApprove(false)"
        >Replace</button>
      </template>
      <button
        v-else-if="cellState === 'approved'"
        type="button"
        class="bg-blue-500/15 border border-blue-500/50 text-blue-400 text-[11px] font-medium px-2 py-1 rounded hover:bg-blue-500/25 transition-colors"
        title="Click to unapprove"
        @click.stop="unapprove"
      >Approved</button>
      <span
        v-else-if="cellState === 'pending'"
        class="text-[11px] text-content-muted text-center"
      >Waiting…</span>
      <button
        v-else-if="cellState === 'failed'"
        type="button"
        class="text-[11px] px-2 py-1 rounded-md bg-overlay-subtle text-content-muted hover:text-content hover:bg-overlay-hover transition-colors"
        @click.stop="$emit('invalidate', invalidateKey || '')"
      >Retry ↻</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import FlowResultPreview from './FlowResultPreview.vue'
import {
  candidateProducerForSlot,
  type GroupedIteration,
} from '../../composables/useFlowGrouping'
import type { FlowEquation, FlowTask } from '../../composables/useFlowsApi'

interface Props {
  approveEquation: FlowEquation | null
  slotIteration: GroupedIteration
  tasksByEquationKey: Map<string, FlowTask[]>
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'resolve-task', task: FlowTask, resolution: any): void
  (e: 'invalidate', equationKey: string): void
}>()

const pendingApproveTask = computed<FlowTask | null>(() => {
  const eq = props.approveEquation
  if (!eq) return null
  const tasks = props.tasksByEquationKey.get(eq.equation_key)
  if (!tasks) return null
  for (const t of tasks) {
    if (t.task_type === 'approve' && t.status === 'pending') return t
  }
  return null
})

const candidateProducer = computed<FlowEquation | null>(
  () => candidateProducerForSlot(props.slotIteration),
)

const hasContent = computed<boolean>(() => {
  const r = candidateProducer.value?.result
  if (r == null) return false
  if (typeof r === 'string') return r.trim().length > 0
  return true
})

type CellState = 'awaiting' | 'approved' | 'pending' | 'failed'
const cellState = computed<CellState>(() => {
  const eq = props.approveEquation
  if (eq?.status === 'failed') return 'failed'
  if (eq?.status === 'completed' && eq.result !== false) return 'approved'
  if (pendingApproveTask.value) return 'awaiting'
  return 'pending'
})

const replaceEquationKey = computed<string | null>(() => {
  return props.slotIteration.wrapperKey
    ?? candidateProducer.value?.equation_key
    ?? props.slotIteration.primary?.equation_key
    ?? null
})
const invalidateKey = computed<string | null>(
  () => props.approveEquation?.equation_key ?? replaceEquationKey.value,
)

function submitApprove(approved: boolean) {
  if (approved) {
    const t = pendingApproveTask.value
    if (!t) return
    emit('resolve-task', t, true)
    return
  }
  // Replace: in `awaiting` state we have a live approve task and
  // prefer the runtime's reject route; in `approved` state there's
  // no pending task to resolve, so invalidate the candidate producer
  // directly to trigger regeneration.
  if (cellState.value === 'awaiting') {
    const t = pendingApproveTask.value
    if (t) emit('resolve-task', t, false)
  } else if (replaceEquationKey.value) {
    emit('invalidate', replaceEquationKey.value)
  }
}

function unapprove() {
  if (props.approveEquation?.equation_key) {
    emit('invalidate', props.approveEquation.equation_key)
  }
}

const frameClass = computed(() => {
  switch (cellState.value) {
    case 'failed':   return 'border-red-500/50 bg-red-500/5'
    case 'awaiting': return 'border-purple-500/50 ring-1 ring-purple-500/30 bg-purple-500/5'
    case 'approved': return 'border-blue-500/30 bg-overlay-faint'
    default:         return 'border-edge-subtle'
  }
})
</script>
