<template>
  <!-- One sub-step row inside a hitl.approve body. Mirrors the lighter
       step-row chrome (status icon + title + count pill + status label).
       The cell renderer depends on the sub-step's kind. -->
  <div :class="rootBgClass">
    <div
      class="w-full flex items-center gap-2.5 px-2.5 py-1.5 text-[12px] text-left"
    >
      <span
        v-if="status === 'computing'"
        class="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0"
      />
      <span
        v-else-if="status === 'actionable'"
        class="w-2 h-2 rounded-full bg-purple-400 flex-shrink-0"
      />
      <svg
        v-else-if="status === 'failed'"
        class="w-3.5 h-3.5 text-red-400 flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      <svg
        v-else-if="status === 'completed'"
        class="w-4 h-4 text-green-500 flex-shrink-0"
        fill="currentColor" viewBox="0 0 24 24"
      >
        <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
      </svg>
      <span v-else class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0" />

      <div class="flex-1 min-w-0 flex flex-col justify-center">
        <div class="flex items-baseline gap-2 min-w-0">
          <span class="truncate text-[12.5px] leading-tight text-content">{{ titleText }}</span>
          <span
            v-if="subtitleText"
            class="truncate text-[11px] leading-tight text-content-muted"
          >{{ subtitleText }}</span>
          <span
            class="inline-flex flex-shrink-0 items-center rounded-full border border-edge-subtle bg-surface-raised px-1.5 py-0.5 text-[10px] font-medium leading-none text-content-secondary shadow-sm"
          >×{{ subStep.iterations.length }}</span>
        </div>
      </div>

      <span
        class="flex-shrink-0 text-[10.5px] font-semibold uppercase tracking-wide tabular-nums w-[72px] text-right"
        :class="statusColor"
      >{{ statusLabel || '' }}</span>
    </div>

    <!-- Body: per-sub-step cell grid. -->
    <div
      class="grid gap-2 px-2 pb-2"
      :class="gridColsClass"
    >
      <template v-if="subStep.kind === 'hitl-approve'">
        <SlotApproveCell
          v-for="(it, i) in subStep.iterations"
          :key="it.wrapperKey"
          :approve-equation="subStep.equations[i]"
          :slot-iteration="parentSlots[i]"
          :slot-index="i + 1"
          :tasks-by-equation-key="tasksByEquationKey"
          @resolve-task="(t, r) => $emit('resolve-task', t, r)"
          @invalidate="(k) => $emit('invalidate-equation', k)"
        />
      </template>
      <template v-else-if="subStep.kind === 'producer'">
        <IterationCard
          v-for="it in subStep.iterations"
          :key="it.wrapperKey"
          :iteration="it"
          size="compact"
          @open="() => {}"
          @invalidate="(k) => $emit('invalidate-equation', k)"
        />
      </template>
      <template v-else>
        <!-- Other equation types — minimal placeholder so the user
             knows there's a step here without the row dominating. -->
        <div
          v-for="it in subStep.iterations"
          :key="it.wrapperKey"
          class="rounded-md border border-edge-subtle bg-overlay-faint px-2 py-1.5 text-[11px] text-content-muted text-center"
        >{{ statusBadge(it.status) }}</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import IterationCard from './IterationCard.vue'
import SlotApproveCell from './SlotApproveCell.vue'
import type { GroupedIteration, SlotSubStep } from '../../composables/useFlowGrouping'
import type { FlowTask } from '../../composables/useFlowsApi'

interface Props {
  subStep: SlotSubStep
  // The original slots — needed by SlotApproveCell so it can find the
  // candidate's media via siblings of the approve equation. The order
  // matches subStep.iterations index-for-index.
  parentSlots: GroupedIteration[]
  tasksByEquationKey: Map<string, FlowTask[]>
}
const props = defineProps<Props>()
defineEmits<{
  (e: 'invalidate-equation', key: string): void
  (e: 'resolve-task', task: FlowTask, resolution: any): void
}>()

const status = computed<'computing' | 'actionable' | 'failed' | 'completed' | 'pending'>(() => {
  const a = props.subStep.aggregate
  if (a.actionable > 0) return 'actionable'
  if (a.failed > 0) return 'failed'
  if (a.computing > 0) return 'computing'
  if (a.total > 0 && a.completed === a.total) return 'completed'
  return 'pending'
})

const statusLabel = computed<string | null>(() => {
  switch (status.value) {
    case 'completed':  return null
    case 'actionable': return 'Your Turn'
    case 'computing':  return 'Running'
    case 'failed':     return 'Failed'
    default:           return null
  }
})
const statusColor = computed<string>(() => {
  switch (status.value) {
    case 'completed':  return 'text-green-500'
    case 'actionable': return 'text-purple-500'
    case 'computing':  return 'text-blue-500'
    case 'failed':     return 'text-red-500'
    default:           return 'text-content-muted'
  }
})
const rootBgClass = computed<string>(() => {
  switch (status.value) {
    case 'actionable': return 'bg-purple-500/5'
    case 'failed':     return 'bg-red-500/5'
    case 'computing':  return 'bg-blue-500/5'
    default:           return ''
  }
})

const titleText = computed<string>(() => props.subStep.displayName)
const subtitleText = computed<string>(() => {
  const ss = props.subStep
  if (ss.kind === 'hitl-approve') return 'Review'
  // For tool/llm/code, the row's name + ×N is enough — no provider line
  // here (the chrome is intentionally lighter than top-level rows).
  return ''
})

const gridColsClass = computed<string>(() => {
  const n = props.subStep.iterations.length
  if (n <= 2) return 'grid-cols-2'
  if (n <= 3) return 'grid-cols-3'
  if (n <= 4) return 'grid-cols-4'
  if (n <= 6) return 'grid-cols-3 sm:grid-cols-6'
  return 'grid-cols-4 sm:grid-cols-6 md:grid-cols-8'
})

function statusBadge(s: string): string {
  switch (s) {
    case 'completed': return 'Done'
    case 'failed':    return 'Failed'
    case 'computing': return 'Running'
    case 'pending':   return 'Queued'
    default:          return s
  }
}
</script>
