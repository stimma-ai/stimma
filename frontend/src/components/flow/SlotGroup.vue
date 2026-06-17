<template>
  <div class="group" :class="rootBgClass">
    <!-- Header row — same chrome shape as IterationGroup so the eye reads
         a consistent right-aligned column set, but the labels reflect the
         primitive's contract: "X of N approved" instead of "× N". -->
    <div
      class="w-full flex items-center gap-2.5 px-2.5 py-1.5 text-[12px] text-left cursor-default"
    >
      <span
        v-if="overallStatus === 'computing'"
        class="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0"
      />
      <span
        v-else-if="overallStatus === 'actionable'"
        class="w-2 h-2 rounded-full bg-purple-400 flex-shrink-0"
      />
      <svg
        v-else-if="overallStatus === 'failed'"
        class="w-3.5 h-3.5 text-red-400 flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      <svg
        v-else-if="overallStatus === 'completed'"
        class="w-4 h-4 text-green-500 flex-shrink-0"
        fill="currentColor" viewBox="0 0 24 24"
      >
        <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
      </svg>
      <span v-else class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0" />

      <!-- Purple HITL gradient icon, matching the existing HITL row chrome.
           hitl.approve is conceptually an HITL primitive: its terminal step
           is always a user approval. -->
      <div
        class="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 bg-gradient-to-br from-purple-500/80 to-purple-700/80"
      >
        <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
        </svg>
      </div>

      <div class="flex-1 min-w-0 flex flex-col justify-center">
        <div class="flex items-baseline gap-2 min-w-0">
          <span class="truncate text-[13px] leading-tight text-content">{{ titleText }}</span>
          <span
            class="inline-flex flex-shrink-0 items-center rounded-full border border-edge-subtle bg-surface-raised px-2 py-0.5 text-[10px] font-medium leading-none text-content-secondary shadow-sm"
          >{{ approvedCount }} of {{ group.count }} approved</span>
        </div>
      </div>

      <!-- Right-aligned columns: status label, duration, re-run for the
           whole hitl.approve block. Re-run blows away every slot's
           generator + approve and starts over — useful when the
           parameters of `generate` were edited upstream. -->
      <span
        class="flex-shrink-0 text-[10.5px] font-semibold uppercase tracking-wide tabular-nums w-[72px] text-right"
        :class="statusColor"
      >{{ statusLabel || '' }}</span>
      <span
        class="flex-shrink-0 text-[11.5px] text-content-muted tabular-nums w-14 text-right"
      >{{ totalDurationLabel || '' }}</span>
      <button
        type="button"
        class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded border border-edge-subtle bg-base text-content-muted hover:text-content hover:bg-overlay-hover"
        title="Re-run all slots"
        @click.stop="$emit('invalidate-equation', group.approve.equation_key)"
      >
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
        </svg>
      </button>
    </div>

    <!-- Body. Transposed: instead of N cells each containing the whole
         slot sub-graph, the body shows one row per equation-position
         within a slot, with N parallel iteration cells underneath. This
         mirrors how phases render their step sequence at the top level
         (hitl.approve is a "virtual phase" whose steps run in parallel
         across slots). -->
    <div class="border-t border-edge-subtle bg-overlay-subtle/20">
      <!-- Instructions: rendered once at the top of the body. The
           string lives on the hitl.approve primitive (not on each task),
           so there's nothing to dedupe — single source of truth. -->
      <div
        v-if="group.instructions"
        class="px-3 py-2 border-b border-edge-subtle bg-purple-500/10 text-[12px] text-content whitespace-pre-wrap"
      >{{ group.instructions }}</div>

      <div class="divide-y divide-edge-subtle">
        <SlotSubStep
          v-for="sub in group.subSteps"
          :key="sub.relativePath"
          :sub-step="sub"
          :parent-slots="group.slots"
          :tasks-by-equation-key="tasksByEquationKey"
          @resolve-task="(t, r) => $emit('resolve-task', t, r)"
          @invalidate-equation="(k) => $emit('invalidate-equation', k)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import SlotSubStep from './SlotSubStep.vue'
import type { SlotGroupItem } from '../../composables/useFlowGrouping'
import type { FlowTask } from '../../composables/useFlowsApi'

interface Props {
  group: SlotGroupItem
  tasksByEquationKey: Map<string, FlowTask[]>
}
const props = defineProps<Props>()
defineEmits<{
  (e: 'invalidate-equation', key: string): void
  (e: 'resolve-task', task: FlowTask, resolution: any): void
}>()

const titleText = computed<string>(() => {
  const dn = (props.group.approve as any).display_name as string | undefined
  if (dn && dn.trim()) return dn
  return 'Pick favorites'
})

const approvedCount = computed(() => props.group.aggregate.completed)

const overallStatus = computed<'computing' | 'actionable' | 'failed' | 'completed' | 'pending'>(() => {
  const a = props.group.aggregate
  if (a.actionable > 0) return 'actionable'
  if (a.failed > 0) return 'failed'
  if (a.computing > 0) return 'computing'
  if (a.total > 0 && a.completed === a.total) return 'completed'
  return 'pending'
})

const statusLabel = computed<string | null>(() => {
  switch (overallStatus.value) {
    case 'completed':  return null
    case 'actionable': return 'Your Turn'
    case 'computing':  return 'Running'
    case 'failed':     return 'Failed'
    default:           return null
  }
})

const statusColor = computed<string>(() => {
  switch (overallStatus.value) {
    case 'completed':  return 'text-green-500'
    case 'actionable': return 'text-purple-500'
    case 'computing':  return 'text-blue-500'
    case 'failed':     return 'text-red-500'
    default:           return 'text-content-muted'
  }
})

const rootBgClass = computed<string>(() => {
  switch (overallStatus.value) {
    case 'actionable': return 'bg-purple-500/5'
    case 'failed':     return 'bg-red-500/5'
    case 'computing':  return 'bg-blue-500/5'
    default:           return ''
  }
})

const totalDurationLabel = computed<string | null>(() => {
  const ms = props.group.totalDurationMs
  if (ms == null) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

</script>
