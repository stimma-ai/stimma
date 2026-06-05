<template>
  <div
    class="bg-overlay-subtle border rounded-lg px-3 py-2.5 transition-all"
    :class="[
      focused ? 'border-blue-500 ring-1 ring-blue-500/50' : 'border-edge',
      resolving ? 'opacity-60 pointer-events-none' : '',
    ]"
    :data-task-id="task.task_id"
    tabindex="0"
    ref="rootEl"
    @focus="$emit('focus', task)"
  >
    <!-- Header: type + phase + unblocks -->
    <div class="flex items-center gap-2 mb-2">
      <span
        class="text-[10px] uppercase font-semibold tracking-wide px-1.5 py-0.5 rounded"
        :class="typeBadgeClass"
      >{{ task.task_type }}</span>
      <span v-if="task.phase_path?.length" class="text-[11px] text-content-muted truncate">
        {{ task.phase_path.join(' / ') }}
      </span>
      <span v-if="task.recipe_name && showRecipe" class="text-[11px] text-blue-400 truncate">
        · {{ task.recipe_name }}
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
        <span class="w-3.5 h-3.5 border border-content-muted border-t-transparent rounded-full animate-spin flex-shrink-0"></span>
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

    <!-- Waiting for tool -->
    <div v-else-if="task.task_type === 'waiting_for_tool'" class="space-y-2">
      <div class="bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5 text-[12px] text-amber-400 flex items-start gap-2">
        <span class="w-3.5 h-3.5 border border-amber-400 border-t-transparent rounded-full animate-spin flex-shrink-0 mt-0.5"></span>
        <div class="whitespace-pre-wrap flex-1">
          <span v-if="waitingToolId">Waiting for tool <code class="text-amber-300">{{ waitingToolId }}</code> to become available.</span>
          <span v-else>Waiting for a tool to become available.</span>
        </div>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          class="bg-overlay-subtle border border-edge text-content text-xs font-medium px-3 py-1 rounded hover:bg-overlay-hover transition-colors"
          @click="submitErrorAction('skip')"
          v-if="taskInLoop"
        >Skip</button>
        <button
          class="bg-overlay-subtle border border-edge text-content text-xs font-medium px-3 py-1 rounded hover:bg-overlay-hover transition-colors"
          @click="$emit('edit-recipe', task)"
        >Edit recipe</button>
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
          class="bg-blue-500 text-white text-xs font-medium px-3 py-1 rounded hover:bg-blue-600 transition-colors"
          @click="$emit('fix-step-with-agent', task)"
        >Ask the agent for help</button>
        <button
          class="bg-overlay-subtle border border-edge text-content text-xs font-medium px-3 py-1 rounded hover:bg-overlay-hover transition-colors"
          @click="submitErrorAction('retry')"
        >Retry</button>
        <button
          class="bg-overlay-subtle border border-edge text-content text-xs font-medium px-3 py-1 rounded hover:bg-overlay-hover transition-colors"
          @click="submitErrorAction('skip')"
        >Skip</button>
        <button
          class="bg-overlay-subtle border border-edge text-content text-xs font-medium px-3 py-1 rounded hover:bg-overlay-hover transition-colors"
          @click="$emit('edit-recipe', task)"
        >Edit recipe</button>
      </div>
      <div
        v-if="devMode && task.error"
        class="rounded border border-amber-500/40 bg-overlay-light text-[11px] font-mono text-content-secondary"
      >
        <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-amber-500/30">
          <span class="text-[9px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-sm">Dev</span>
          <span class="text-content-muted">raw step error</span>
          <span class="flex-1" />
          <span class="text-content-muted truncate">{{ task.equation_key }}</span>
        </div>
        <pre class="px-2.5 py-2 whitespace-pre-wrap break-words" :class="devErrorClass">{{ task.error }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import HitlActionCard from './HitlActionCard.vue'
import HitlSelectInline from './HitlSelectInline.vue'
import type { RecipeTask } from '../../composables/useRecipesApi'
import { parseRecipeError } from '../../utils/recipeErrors'

interface Props {
  task: RecipeTask
  focused?: boolean
  showRecipe?: boolean
  devMode?: boolean
  allowInnerScroll?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  focused: false,
  showRecipe: false,
  devMode: false,
  allowInnerScroll: true,
})
const emit = defineEmits<{
  (e: 'resolve', task: RecipeTask, resolution: any): void
  (e: 'resolve-error', task: RecipeTask, action: string, value?: any): void
  (e: 'focus', task: RecipeTask): void
  (e: 'edit-recipe', task: RecipeTask): void
  (e: 'fix-step-with-agent', task: RecipeTask): void
}>()

const rootEl = ref<HTMLElement | null>(null)
const resolving = ref(false)
const parsedTaskError = computed(() =>
  parseRecipeError(props.task.error || props.task.payload?.error_message || props.task.instructions),
)
const devErrorClass = computed(() =>
  props.allowInnerScroll ? 'max-h-60 overflow-y-auto custom-scrollbar' : '',
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
const typeBadgeClass = computed(() => {
  switch (props.task.task_type) {
    case 'select': return 'bg-blue-500/20 text-blue-400'
    case 'approve': return 'bg-green-500/20 text-green-400'
    case 'error': return 'bg-red-500/20 text-red-400'
    case 'waiting_for_tool': return 'bg-amber-500/20 text-amber-400'
    default: return 'bg-overlay-hover text-content-muted'
  }
})

const waitingToolId = computed<string | null>(() => {
  const payload = props.task.payload || {}
  const id = payload.tool_id
  return typeof id === 'string' && id ? id : null
})

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
