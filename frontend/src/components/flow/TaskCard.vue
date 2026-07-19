<template>
  <div
    class="bg-surface-raised rounded-lg shadow-lg px-3 py-3 transition-all"
    :class="[
      focused ? 'ring-2 ring-blue-500/60' : '',
      resolving ? 'opacity-60 pointer-events-none' : '',
    ]"
    :data-task-id="task.task_id"
    tabindex="0"
    ref="rootEl"
    @focus="$emit('focus', task)"
  >
    <!-- Header: type + phase + unblocks -->
    <div class="flex items-center gap-2 mb-2">
      <StatusDot v-if="task.task_type === 'waiting_for_tool'" bucket="warning" />
      <StatusDot v-else-if="task.task_type !== 'error'" bucket="awaiting" pulse />
      <span
        class="font-mono text-[10px] font-semibold px-1.5 py-0.5 rounded"
        :class="typeBadgeClass"
      >{{ taskTypeLabel }}</span>
      <span v-if="task.phase_path?.length" class="text-[11px] text-content-muted truncate">
        {{ task.phase_path.join(' / ') }}
      </span>
      <span v-if="task.flow_name && showFlow" class="text-[11px] text-blue-400 truncate">
        · {{ task.flow_name }}
      </span>
      <span v-if="task.downstream_count > 0" class="ml-auto text-[11px] text-content-tertiary whitespace-nowrap">
        unblocks {{ task.downstream_count }}
      </span>
    </div>

    <!-- Instructions -->
    <p v-if="task.instructions" class="text-[13px] text-content mb-2 whitespace-pre-wrap">
      {{ task.instructions }}
    </p>

    <!-- Select — kept tiles + Browse pool button. The candidate grid
         itself lives in HitlBrowseSheet (a modal), keeping the timeline
         row compact. HitlSelectInline mirrors the slot row that
         hitl.approve produces, so the two HITL primitives read with the
         same visual rhythm in the timeline. -->
    <div v-if="task.task_type === 'select'">
      <div v-if="selectCandidatesRaw.length === 0" class="flex items-center gap-2 py-2 text-[12px] text-content-muted">
        <Spinner size="sm" hue="border-t-content-muted" class="flex-shrink-0" />
        Waiting for results to be ready…
      </div>
      <HitlSelectInline
        v-else
        :candidates="selectCandidatesRaw"
        :count="selectCount"
        mode="task"
        @resolve="submitSelectResolution"
      />
    </div>

    <!-- Approve — uses the shared HitlActionCard so the task-list
         rendering matches the per-slot approve cells in the slot grid.
         The task is always in the awaiting state by the time it reaches
         TaskCard (resolved tasks are filtered out upstream). Capped at
         max-w-sm so a single approve doesn't blow up to full width when
         the containing column is wide. -->
    <div v-else-if="task.task_type === 'approve'" class="max-w-sm">
      <HitlActionCard
        mode="approve"
        :media-id="approveMediaId"
        state="awaiting"
        @approve="submitApprove"
      />
    </div>

    <!-- Tool unavailable -->
    <div v-else-if="task.task_type === 'waiting_for_tool'" class="space-y-2">
      <div class="bg-amber-500/10 rounded-md px-2 py-1.5 text-[12px] text-amber-500 flex items-start gap-2">
        <svg class="mt-0.5 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.008v.008H12v-.008z" />
        </svg>
        <div class="whitespace-pre-wrap flex-1">
          <span v-if="needsStimmaLogin">This Stimma tool is unavailable because you're signed out.</span>
          <span v-else-if="waitingToolId">Tool <code>{{ waitingToolId }}</code> is unavailable. The flow will resume when it comes back online.</span>
          <span v-else>A tool is unavailable. The flow will resume when it comes back online.</span>
        </div>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          v-if="needsStimmaLogin"
          type="button"
          class="rounded-md bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-3 py-1 text-xs font-medium text-white transition-colors hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400"
          @click="openCloudLogin"
        >Log in to Stimma</button>
        <button
          class="bg-overlay-subtle text-content text-xs font-medium px-3 py-1 rounded-md hover:bg-overlay-hover transition-colors"
          @click="submitErrorAction('skip')"
          v-if="taskInLoop"
        >Skip</button>
        <button
          class="bg-overlay-subtle text-content text-xs font-medium px-3 py-1 rounded-md hover:bg-overlay-hover transition-colors"
          @click="$emit('edit-flow', task)"
        >Edit flow</button>
      </div>
    </div>

    <!-- Error task -->
    <div v-else-if="task.task_type === 'error'" class="space-y-2">
      <div class="rounded border border-red-500/30 bg-red-500/5 px-2.5 py-2">
        <div class="text-[12px] font-semibold text-red-400">{{ parsedTaskError?.title || 'This step failed' }}</div>
        <div
          v-if="parsedTaskError?.message"
          class="mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-content-secondary"
        >
          {{ parsedTaskError.message }}
        </div>
      </div>
      <div v-if="task.dependencies?.length" class="text-[11px] text-content-muted">
        Upstream: {{ task.dependencies.join(', ') }}
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          class="bg-accent text-white text-xs font-medium px-3 py-1 rounded-md hover:bg-accent/90 transition-colors"
          @click="$emit('fix-step-with-agent', task)"
        >Ask the agent for help</button>
        <button
          class="bg-overlay-subtle text-content text-xs font-medium px-3 py-1 rounded-md hover:bg-overlay-hover transition-colors"
          @click="submitErrorAction('retry')"
        >Retry</button>
        <button
          class="bg-overlay-subtle text-content text-xs font-medium px-3 py-1 rounded-md hover:bg-overlay-hover transition-colors"
          @click="submitErrorAction('skip')"
        >Skip</button>
        <button
          class="bg-overlay-subtle text-content text-xs font-medium px-3 py-1 rounded-md hover:bg-overlay-hover transition-colors"
          @click="$emit('edit-flow', task)"
        >Edit flow</button>
      </div>
      <div
        v-if="devMode && task.error"
        class="rounded border border-amber-500/40 bg-overlay-light text-[11px] font-mono text-content-secondary"
      >
        <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-amber-500/30">
          <span class="text-[9px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-md">Dev</span>
          <span class="text-content-muted">raw step error</span>
          <span class="flex-1" />
          <span class="text-content-muted truncate">{{ task.equation_key }}</span>
        </div>
        <pre class="px-2.5 py-2 whitespace-pre-wrap break-words select-text" :class="devErrorClass">{{ task.error }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import HitlActionCard from './HitlActionCard.vue'
import HitlSelectInline from './HitlSelectInline.vue'
import StatusDot from '../ui/StatusDot.vue'
import Spinner from '../ui/Spinner.vue'
import type { FlowTask } from '../../composables/useFlowsApi'
import { parseFlowError } from '../../utils/flowErrors'
import { formatTaskTypeLabel } from '../../utils/taskTypeIcons'
import { bgClass, textClass, type StatusBucket } from '../../utils/statusColors'
import { useAuth } from '../../composables/useAuth'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'

interface Props {
  task: FlowTask
  focused?: boolean
  showFlow?: boolean
  devMode?: boolean
  allowInnerScroll?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  focused: false,
  showFlow: false,
  devMode: false,
  allowInnerScroll: true,
})
const emit = defineEmits<{
  (e: 'resolve', task: FlowTask, resolution: any): void
  (e: 'resolve-error', task: FlowTask, action: string, value?: any): void
  (e: 'focus', task: FlowTask): void
  (e: 'edit-flow', task: FlowTask): void
  (e: 'fix-step-with-agent', task: FlowTask): void
}>()

const rootEl = ref<HTMLElement | null>(null)
const resolving = ref(false)
const parsedTaskError = computed(() =>
  parseFlowError(props.task.error || props.task.payload?.error_message || props.task.instructions),
)
const devErrorClass = computed(() =>
  props.allowInnerScroll ? 'max-h-60 overflow-y-auto custom-scrollbar' : '',
)
const taskTypeLabel = computed(() =>
  props.task.task_type === 'waiting_for_tool'
    ? 'Tool unavailable'
    : formatTaskTypeLabel(props.task.task_type),
)

// ----- Select -----
const selectCandidatesRaw = computed<any[]>(() => {
  const payload = props.task.payload || {}
  if (Array.isArray(payload.candidates)) return payload.candidates
  if (Array.isArray(payload.options)) return payload.options
  return []
})
const selectCount = computed(() => Number((props.task.payload as any)?.count ?? 1))

function submitSelectResolution(resolution: any) {
  if (resolving.value) return
  resolving.value = true
  emit('resolve', props.task, resolution)
}

// ----- Approve -----
const approveMediaId = computed<number | null>(() => {
  const payload: any = props.task.payload || {}
  const mid = payload.media_id ?? payload.mediaId ?? payload.asset?.media_id ?? payload.asset
  return typeof mid === 'number' ? mid : null
})
function submitApprove(approved: boolean) {
  if (resolving.value) return
  resolving.value = true
  emit('resolve', props.task, approved)
}

// ----- Error -----
function submitErrorAction(action: string, value?: any) {
  if (resolving.value) return
  resolving.value = true
  emit('resolve-error', props.task, action, value)
}

// ----- Type badge -----
// Task-type buckets, routed through statusColors.ts (STANDARDS 1.9) rather
// than an inline switch of raw color classes: select reads as an open
// decision (running/blue), approve as a settled ask (done/green), error as
// failed (red), waiting_for_tool as non-fatal trouble (warning/amber).
function taskTypeBucket(taskType: string): StatusBucket | null {
  switch (taskType) {
    case 'select': return 'running'
    case 'approve': return 'done'
    case 'error': return 'failed'
    case 'waiting_for_tool': return 'warning'
    default: return null
  }
}
const typeBadgeClass = computed(() => {
  const bucket = taskTypeBucket(props.task.task_type)
  return bucket ? `${bgClass(bucket)} ${textClass(bucket)}` : 'bg-overlay-hover text-content-muted'
})

const waitingToolId = computed<string | null>(() => {
  const payload = props.task.payload || {}
  const id = payload.tool_id
  return typeof id === 'string' && id ? id : null
})

const { isAuthenticated } = useAuth()
const needsStimmaLogin = computed(() =>
  waitingToolId.value?.split(':')[0] === STIMMA_CLOUD_PROVIDER_ID
  && !isAuthenticated.value,
)

function openCloudLogin() {
  window.dispatchEvent(new CustomEvent('open-settings', { detail: 'account' }))
}

const taskInLoop = computed(() => {
  // Heuristic mirror of backend _is_inside_foreach_iteration: iteration keys
  // carry a segment starting with "@" in the equation key path.
  return (props.task.equation_key || '').split('/').some(seg => seg.startsWith('@'))
})

// ----- Keyboard API exposed to parent -----
function handleKey(e: KeyboardEvent): boolean {
  if (props.task.task_type === 'approve') {
    if (e.key === 'Enter' || e.key === 'ArrowUp') { submitApprove(true); return true }
    if (e.key === 'ArrowDown' || e.key.toLowerCase() === 'r' || e.key === 'Backspace') {
      submitApprove(false); return true
    }
  } else if (props.task.task_type === 'error') {
    if (e.key === 'Enter') { submitErrorAction('retry'); return true }
    if (e.key.toLowerCase() === 's') { submitErrorAction('skip'); return true }
  }
  // Select tasks no longer handle inline keyboard nav — the candidate grid
  // moved into the modal sheet, which manages its own focus and keys.
  return false
}
defineExpose({ handleKey, el: rootEl })
</script>
