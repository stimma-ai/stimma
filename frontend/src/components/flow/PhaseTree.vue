<template>
  <div class="phase-tree">
    <div v-if="!loadError && (!root || (root.equation_keys?.length === 0 && root.children?.length === 0))" class="py-8 text-center">
      <div class="mx-auto max-w-md space-y-3">
        <div class="text-[15px] font-medium text-content">No steps yet.</div>
        <div class="text-[13px] text-content-muted leading-relaxed">
          Ask the assistant to build this flow. The steps and inputs will appear here.
        </div>
      </div>
    </div>

    <PhaseNode
      v-else
      :node="root"
      :depth="0"
      :equations-by-key="equationsByKey"
      :tasks-by-equation-key="tasksByEquationKey"
      :focused-task-id="focusedTaskId"
      :execution-state="executionState"
      :dev-mode="devMode"
      @invalidate-phase="(p) => $emit('invalidate-phase', p)"
      @invalidate-equation="(k) => $emit('invalidate-equation', k)"
      @reselect-equation="(k, r) => $emit('reselect-equation', k, r)"
      @resolve-task="(t, r) => $emit('resolve-task', t, r)"
      @resolve-error-task="(t, a, v) => $emit('resolve-error-task', t, a, v)"
      @focus-task="(t) => $emit('focus-task', t)"
      @edit-flow="(t) => $emit('edit-flow', t)"
      @register-task-ref="(id, el) => $emit('register-task-ref', id, el)"
      @fix-step-with-agent="(e) => $emit('fix-step-with-agent', e)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import PhaseNode from './PhaseNode.vue'
import type { PhaseNode as PhaseNodeType, FlowEquation, FlowTask } from '../../composables/useFlowsApi'

interface Props {
  root: PhaseNodeType | null
  equationsByKey: Map<string, FlowEquation>
  tasks: FlowTask[]
  focusedTaskId?: string | null
  loadError?: { category: string; message: string; suggestion?: string | null } | null
  executionState?: string
  devMode?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  focusedTaskId: null, loadError: null, executionState: 'idle', devMode: false,
})
defineEmits<{
  (e: 'invalidate-phase', path: string[]): void
  (e: 'invalidate-equation', key: string): void
  (e: 'reselect-equation', key: string, resolution: any): void
  (e: 'resolve-task', task: FlowTask, resolution: any): void
  (e: 'resolve-error-task', task: FlowTask, action: string, value?: any): void
  (e: 'focus-task', task: FlowTask): void
  (e: 'edit-flow', task: FlowTask): void
  (e: 'register-task-ref', taskId: string, el: any): void
  (e: 'fix-step-with-agent', equation: FlowEquation): void
}>()

const tasksByEquationKey = computed<Map<string, FlowTask[]>>(() => {
  const m = new Map<string, FlowTask[]>()
  for (const t of props.tasks) {
    const k = t.equation_key
    if (!m.has(k)) m.set(k, [])
    m.get(k)!.push(t)
  }
  return m
})
</script>
