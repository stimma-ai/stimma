<template>
  <!-- Fill_slots-context wrapper around HitlActionCard. Resolves
       state from the slot's approve equation + pending task lookup,
       finds candidate media via siblings (the auto-injected approve
       mirrors its asset but its own result_media_ids is empty
       pre-completion), and wires the action emits to the equation
       graph. The visual is owned by HitlActionCard so this row reads
       identical to a standalone hitl.approve card. -->
  <HitlActionCard
    mode="approve"
    :media-id="thumbMediaId"
    :state="cellState"
    :label="`Slot ${slotIndex}`"
    @approve="(ok) => submitApprove(ok)"
    @unapprove="unapprove"
    @retry="$emit('invalidate', invalidateKey)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import HitlActionCard from './HitlActionCard.vue'
import {
  candidateProducerForSlot,
  type GroupedIteration,
} from '../../composables/useFlowGrouping'
import type { FlowEquation, FlowTask } from '../../composables/useFlowsApi'

interface Props {
  approveEquation: FlowEquation | null
  // The parent slot's iteration. Used to find candidate media via
  // siblings of the approve equation, since approve's own
  // result_media_ids is empty until the user has approved it.
  slotIteration: GroupedIteration
  slotIndex: number
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

const candidateProducer = computed<FlowEquation | null>(() => {
  return candidateProducerForSlot(props.slotIteration)
})
const thumbMediaId = computed<number | null>(() => {
  return candidateProducer.value?.result_media_ids?.[0] ?? null
})

type CellState = 'awaiting' | 'approved' | 'pending' | 'failed'
const cellState = computed<CellState>(() => {
  const eq = props.approveEquation
  // Equation status is the source of truth — task list entries can lag
  // behind the equation transition (a stale pending task left over after
  // the equation already completed would otherwise pin the cell on
  // "Approve / Replace" forever). The Outputs panel reads equation
  // status directly, so trusting it here keeps the two views in sync.
  if (eq?.status === 'failed') return 'failed'
  if (eq?.status === 'completed' && eq.result !== false) return 'approved'
  if (pendingApproveTask.value) return 'awaiting'
  return 'pending'
})

const approveEquationKey = computed<string | null>(
  () => props.approveEquation?.equation_key ?? null,
)
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
  // Replace path. In `awaiting` state we have a live approve task
  // and prefer the runtime's reject route — resolve(task, false)
  // invalidates the upstream and re-asks via a fresh task. In
  // `approved` state there's no pending task to resolve, so
  // invalidate the candidate producer directly to trigger
  // regeneration; the auto-injected approve will re-spawn its task
  // when the new candidate finishes.
  if (cellState.value === 'awaiting') {
    const t = pendingApproveTask.value
    if (t) emit('resolve-task', t, false)
  } else if (replaceEquationKey.value) {
    emit('invalidate', replaceEquationKey.value)
  }
}

function unapprove() {
  if (!approveEquationKey.value) return
  emit('invalidate', approveEquationKey.value)
}
</script>
