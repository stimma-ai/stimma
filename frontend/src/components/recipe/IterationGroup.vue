<template>
  <div class="group" :class="[rootBorderClass, groupIsEchoed ? 'ring-1 ring-blue-500/40 bg-blue-500/5' : '']">
    <!-- Header row — same chrome as individual trace rows -->
    <div
      :role="lockedOpen ? undefined : 'button'"
      :tabindex="lockedOpen ? undefined : 0"
      class="w-full flex items-center gap-2.5 px-2.5 py-1.5 text-[12px] text-left"
      :class="lockedOpen ? 'cursor-default' : 'cursor-pointer'"
      @click="toggleExpanded"
      @keydown.enter.prevent="toggleExpanded"
      @keydown.space.prevent="toggleExpanded"
    >
      <!-- Aggregate status glyph — carries the full state vocabulary alone
           (no separate right-rail label). Distinct glyph + color per state so
           a rolled-up row is triagable from the leftmost column. -->
      <span
        v-if="aggregateStatus === 'computing'"
        class="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0"
        :title="'Running'"
      />
      <span
        v-else-if="aggregateStatus === 'actionable'"
        class="w-2.5 h-2.5 rounded-full bg-purple-500 flex-shrink-0 animate-pulse-soft"
        :title="'Your Turn'"
      />
      <svg
        v-else-if="aggregateStatus === 'failed'"
        class="w-3.5 h-3.5 text-red-400 flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
      >
        <title>Failed</title>
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      <svg
        v-else-if="aggregateStatus === 'completed'"
        class="w-4 h-4 text-green-500 flex-shrink-0"
        fill="currentColor" viewBox="0 0 24 24"
      >
        <title>Done</title>
        <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
      </svg>
      <svg
        v-else-if="aggregateStatus === 'queued'"
        class="w-3.5 h-3.5 text-content-muted flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
      >
        <title>Queued</title>
        <circle cx="12" cy="12" r="9" stroke-linecap="round" stroke-linejoin="round" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 7v5l3 2" />
      </svg>
      <span
        v-else
        class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0"
        :title="'Pending'"
      />

      <!-- Title row: action label + low-emphasis runtime pill (model · provider)
           + multiplicity count + exception-only aggregate text (e.g. "1 failed"
           in red). The pill keeps power-user info visible without making the
           row read as a model identifier. The count pill is kept visually
           distinct so rolled-up rows don't read as "candidates". -->
      <div class="flex-1 min-w-0 flex flex-col justify-center">
        <div class="flex items-baseline gap-2 min-w-0">
          <span class="truncate text-[13px] leading-tight text-content">{{ titleText }}</span>
          <span
            v-if="runtimePill"
            class="flex-shrink-0 truncate text-[10px] leading-none rounded px-1.5 py-0.5 bg-overlay-subtle/50 text-content-muted"
          >
            <span v-if="runtimeModelLabel">{{ runtimeModelLabel }}</span>
            <span v-if="runtimeModelLabel && runtimeProviderLabel"> · </span>
            <span
              v-if="runtimeProviderLabel"
              :class="isStimmaCloud ? 'stimma-cloud-text font-medium' : ''"
            >{{ runtimeProviderLabel }}</span>
          </span>
          <span
            v-if="countPillText"
            class="inline-flex flex-shrink-0 items-center rounded-full border border-edge-subtle bg-surface-raised px-2 py-0.5 text-[10px] font-medium leading-none text-content-secondary shadow-sm"
          >{{ countPillText }}</span>
          <span
            v-if="aggregateExceptionLabel"
            class="truncate text-[11px] leading-tight"
            :class="aggregateExceptionColor"
          >{{ aggregateExceptionLabel }}</span>
        </div>
      </div>

      <!-- Collapsed-state thumbnail strip: surfaces iteration outputs in the
           header so a collapsed group isn't just a count label. Fixed width
           (even when empty) keeps the status column aligned row-to-row. -->
      <div
        v-if="!expanded"
        class="hidden sm:flex flex-shrink-0 items-center justify-end w-32"
      >
        <div
          v-for="(t, i) in headerThumbs"
          :key="t.key"
          class="w-6 h-6 rounded-md border border-surface overflow-hidden ring-1 ring-edge-subtle"
          :class="i > 0 ? '-ml-1.5' : ''"
          :style="{ zIndex: headerThumbs.length - i }"
        >
          <RecipeMediaTile
            :media-id="t.mediaId"
            :thumbnail="true"
            :thumbnail-size="128"
            container-class="w-full h-full"
            img-class="w-full h-full object-cover"
          />
        </div>
      </div>

      <!-- Right-aligned: total duration + re-run button. The status label
           column that used to sit here is gone now that each aggregate state
           has its own leftmost icon (purple pulse, clock, etc.). -->
      <span
        class="flex-shrink-0 text-[11.5px] text-content-muted tabular-nums w-14 text-right"
      >{{ totalDurationLabel || '' }}</span>
      <RecipeRefButton
        v-if="groupRefKey"
        :ref-key="groupRefKey"
        kind="iteration-group"
        :label="titleText"
        :breadcrumb="groupBreadcrumb"
      />
      <button
        v-if="pendingApproveTasks.length > 0"
        type="button"
        class="flex-shrink-0 h-6 px-2 flex items-center justify-center rounded bg-blue-500 text-white border border-blue-500 text-[10.5px] font-semibold hover:bg-blue-600 transition-colors"
        :title="`Approve all ${pendingApproveTasks.length} pending`"
        @click.stop="approveAll"
      >Approve all</button>
      <button
        v-if="invalidateTargetKey"
        type="button"
        class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded border border-edge-subtle bg-base text-content-muted hover:text-content hover:bg-overlay-hover"
        title="Re-run all iterations in this loop"
        @click.stop="$emit('invalidate-equation', invalidateTargetKey)"
      >
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
        </svg>
      </button>
      <span v-else class="flex-shrink-0 w-6 h-6" aria-hidden="true" />
    </div>

    <!-- Body: scale-adaptive. The layout picks itself from iteration count;
         the user can't pick a layout directly (would be one more config knob
         without a clear right default). -->
    <Transition name="recipe-expand">
    <div v-if="expanded">
    <div class="border-t border-edge-subtle bg-overlay-subtle/20">
      <!-- Optional instructions strip — meaningful only for hitl-approve
           groups (auto-injected by hitl.approve). Lives inside the body so
           expand/collapse follows the row's lock-open state. -->
      <div
        v-if="group.instructions"
        class="px-3 py-2 border-b border-edge-subtle bg-purple-500/10 text-[12px] text-content whitespace-pre-wrap"
      >{{ group.instructions }}</div>

      <!-- HITL approve cells: layout depends on contentKind. Media
           candidates use the existing 4-col tile grid (square thumbs +
           buttons). Text candidates render as a vertical row stack so
           multi-line LLM outputs read at full width with the
           Approve/Replace controls pinned right. -->
      <div
        v-if="group.cellMode === 'hitl-approve' && group.contentKind === 'text'"
        class="flex flex-col gap-1.5 p-2"
      >
        <SlotApproveRow
          v-for="(it, i) in sortedIterations"
          :key="it.wrapperKey"
          :approve-equation="it.primary"
          :slot-iteration="(group.parentSlots && group.parentSlots[i]) || it"
          :tasks-by-equation-key="tasksByEquationKey || EMPTY_TASK_MAP"
          @resolve-task="(t, r) => $emit('resolve-task', t, r)"
          @invalidate="(k) => $emit('invalidate-equation', k)"
        />
      </div>
      <div
        v-else-if="group.cellMode === 'hitl-approve'"
        class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-3 lg:grid-cols-4 gap-2 p-2"
      >
        <SlotApproveCell
          v-for="(it, i) in sortedIterations"
          :key="it.wrapperKey"
          :approve-equation="it.primary"
          :slot-iteration="(group.parentSlots && group.parentSlots[i]) || it"
          :slot-index="i + 1"
          :tasks-by-equation-key="tasksByEquationKey || EMPTY_TASK_MAP"
          @resolve-task="(t, r) => $emit('resolve-task', t, r)"
          @invalidate="(k) => $emit('invalidate-equation', k)"
        />
      </div>

      <!-- Producer rows: text iterations (llm() loops, code() with
           non-media output) render as a vertical stack of full-width
           rows. Media iterations keep the tile grid (3→6 cols inline,
           denser at compact, summary ribbon at the high end). -->
      <div
        v-else-if="group.contentKind === 'text' && layoutMode !== 'summary'"
        class="flex flex-col gap-1.5 p-2"
        :style="layoutMode === 'compact' ? 'max-height: 420px; overflow-y: auto;' : undefined"
      >
        <RecipeIterationRow
          v-for="it in sortedIterations"
          :key="it.wrapperKey"
          :iteration="it"
          @open="openIteration"
          @invalidate="(k) => $emit('invalidate-equation', k)"
        />
      </div>
      <div
        v-else-if="layoutMode !== 'summary'"
        class="grid gap-2 p-2"
        :class="gridColsClass"
        :style="layoutMode === 'compact' ? 'max-height: 420px; overflow-y: auto;' : undefined"
      >
        <IterationCard
          v-for="it in sortedIterations"
          :key="it.wrapperKey"
          :iteration="it"
          :size="layoutMode === 'inline' ? 'full' : 'compact'"
          @open="openIteration"
          @invalidate="(k) => $emit('invalidate-equation', k)"
        />
      </div>

      <!-- Summary: status ribbon + actionable preview + optional full grid -->
      <div v-else class="p-2 space-y-2">
        <!-- Ribbon: one small cell per iteration, colored by status -->
        <div class="flex flex-wrap gap-0.5">
          <span
            v-for="it in group.iterations"
            :key="it.wrapperKey"
            class="w-2.5 h-4 rounded-sm cursor-pointer transition hover:scale-110"
            :class="ribbonCellClass(it)"
            :title="`#${it.iterKey} — ${it.status}`"
            @click="openIteration(it)"
          />
        </div>

        <!-- Actionable + recent preview -->
        <div v-if="previewIterations.length">
          <div class="text-[10px] uppercase tracking-wide text-content-muted mb-1">Needs attention</div>
          <div class="grid grid-cols-8 gap-1.5">
            <IterationCard
              v-for="it in previewIterations"
              :key="it.wrapperKey"
              :iteration="it"
              size="compact"
              @open="openIteration"
              @invalidate="(k) => $emit('invalidate-equation', k)"
            />
          </div>
        </div>

        <button
          v-if="!showAllInSummary"
          class="text-[11px] text-content-muted hover:text-content"
          @click="showAllInSummary = true"
        >Show all {{ group.aggregate.total }} iterations →</button>
        <div
          v-if="showAllInSummary"
          class="grid grid-cols-8 gap-1.5"
          style="max-height: 480px; overflow-y: auto;"
        >
          <IterationCard
            v-for="it in sortedIterations"
            :key="it.wrapperKey"
            :iteration="it"
            size="compact"
            @open="openIteration"
            @invalidate="(k) => $emit('invalidate-equation', k)"
          />
        </div>
      </div>

    </div>
    </div>
    </Transition>

    <RecipeIterationModal
      :iteration="openedIteration"
      :recipe-id="recipeId"
      @close="openedIteration = null"
      @invalidate-equation="(k) => $emit('invalidate-equation', k)"
      @fix-step-with-agent="(e) => $emit('fix-step-with-agent', e)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { IterationGroupItem, GroupedIteration } from '../../composables/useRecipeGrouping'
import type { RecipeEquation, RecipeTask } from '../../composables/useRecipesApi'
import { useRecipeExpandState } from '../../composables/useRecipeExpandState'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { TASK_TYPE_LABELS } from '../../utils/taskTypeIcons'
import IterationCard from './IterationCard.vue'
import SlotApproveCell from './SlotApproveCell.vue'
import SlotApproveRow from './SlotApproveRow.vue'
import RecipeIterationRow from './RecipeIterationRow.vue'
import RecipeMediaTile from './RecipeMediaTile.vue'
import RecipeIterationModal from './RecipeIterationModal.vue'
import RecipeRefButton from './RecipeRefButton.vue'
import { useRecipeReferences, injectRecipeChatIdRef } from '../../composables/useRecipeReferences'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'

interface Props {
  group: IterationGroupItem
  recipeId: number | string | null
  isPaused?: boolean
  devMode?: boolean
  // Tasks by equation_key. Required when the group is in
  // cellMode='hitl-approve' so each approve cell can resolve its own
  // pending task. Ignored for tile-mode groups.
  tasksByEquationKey?: Map<string, RecipeTask[]>
}
const props = withDefaults(defineProps<Props>(), {
  isPaused: false, devMode: false, tasksByEquationKey: undefined,
})
const emit = defineEmits<{
  (e: 'invalidate-equation', key: string): void
  (e: 'fix-step-with-agent', equation: RecipeEquation): void
  (e: 'resolve-task', task: RecipeTask, resolution: any): void
}>()

// Empty fallback for the tasksByEquationKey prop in template — keeps
// the v-bind expression strict-typed without nullable arithmetic.
const EMPTY_TASK_MAP: Map<string, RecipeTask[]> = new Map()

const recipeIdRef = computed(() => props.recipeId)
const { isExpanded, toggle } = useRecipeExpandState(recipeIdRef)

// Reference in chat: the iteration group is treated as one rolled-up unit —
// referencing it tells the agent "these N iterations as a whole." The refKey
// is prefixed with `group:` so it doesn't collide with any equation_key
// namespace. Echo class lights the group header when the user hovers the
// matching chip in the context tray.
const recipeRefs = useRecipeReferences(injectRecipeChatIdRef())
const groupRefKey = computed<string | null>(() => {
  const k = props.group.foreach?.equation_key || props.group.groupKey
  return k ? `group:${k}` : null
})
const groupIsEchoed = computed<boolean>(() =>
  !!groupRefKey.value && recipeRefs.hoveredRefKey.value === groupRefKey.value,
)
const groupBreadcrumb = computed<string>(() => {
  const p = props.group.foreach?.phase_path || []
  return p.length > 0 ? `${p[p.length - 1]} · ${props.group.aggregate.total} iterations` : `${props.group.aggregate.total} iterations`
})

const openedIteration = ref<GroupedIteration | null>(null)
const showAllInSummary = ref(false)

// Default-collapsed: the header thumbnail strip already communicates "what
// this produced" for the common case, and the recipe's final outputs
// surface in a dedicated delivery panel at the bottom. Auto-expand is
// reserved for groups the user needs to act on (awaiting input, failed) —
// computing doesn't qualify because the group flips in and out of that
// state as iterations finish, and auto-expanding on it produced a flicker
// across the steps list.
const defaultExpanded = computed(() => {
  const agg = props.group.aggregate
  return agg.actionable > 0 || agg.failed > 0
})
// "Your Turn" rollups are locked open. Collapsing the group while pending
// iterations live inside it would hide the user's only action surface for
// those iterations, stalling the recipe behind a chevron.
const lockedOpen = computed(() => props.group.aggregate.actionable > 0)
const expanded = computed(() => lockedOpen.value || isExpanded('group', props.group.groupKey, defaultExpanded.value))
function toggleExpanded() {
  if (lockedOpen.value) return
  toggle('group', props.group.groupKey, expanded.value)
}

const aggregateStatus = computed<'completed' | 'failed' | 'computing' | 'actionable' | 'queued' | 'pending'>(() => {
  const a = props.group.aggregate
  if (a.actionable > 0) return 'actionable'
  if (a.failed > 0) return 'failed'
  if (a.computing > 0) return 'computing'
  if (a.total > 0 && a.completed === a.total) return 'completed'
  if (a.queued > 0) return 'queued'
  return 'pending'
})

// Color for the inline aggregate-exception text ("1 failed" / "2 awaiting
// you"). Tints to match the aggregate state so the row reads as red/purple
// at a glance without a separate label column.
const aggregateExceptionColor = computed<string>(() => {
  const a = props.group.aggregate
  if (a.failed > 0) return 'text-red-500'
  if (a.actionable > 0) return 'text-purple-500'
  return 'text-content-muted'
})

// Pending approve tasks across the rollup — only meaningful for
// hitl-approve cellMode groups, where each iteration's primary equation
// is the auto-injected approve. Surfaces a header "Approve all" button so
// the user doesn't have to click row-by-row through N parallel slots.
const pendingApproveTasks = computed<RecipeTask[]>(() => {
  if (props.group.cellMode !== 'hitl-approve') return []
  const map = props.tasksByEquationKey
  if (!map) return []
  const out: RecipeTask[] = []
  for (const it of props.group.iterations) {
    const key = it.primary?.equation_key
    if (!key) continue
    const tasks = map.get(key)
    if (!tasks) continue
    for (const t of tasks) {
      if (t.task_type === 'approve' && t.status === 'pending') out.push(t)
    }
  }
  return out
})

function approveAll() {
  for (const t of pendingApproveTasks.value) {
    emit('resolve-task', t, true)
  }
}

// Key used when the header ↻ is clicked — re-run the whole foreach loop.
// Prefer the foreach primitive's equation key (groupKey); fall back to the
// primary equation of the first iteration if the foreach record isn't present.
const invalidateTargetKey = computed<string | null>(() => {
  if (props.group.foreach?.equation_key) return props.group.foreach.equation_key
  if (props.group.groupKey) return props.group.groupKey
  return null
})

// Status tint on the row background; rounding + border now come from the
// enclosing phase card, so rollups read as one of many rows in a list.
const rootBorderClass = computed(() => {
  switch (aggregateStatus.value) {
    case 'failed':    return 'bg-red-500/5'
    case 'computing': return 'bg-blue-500/5'
    case 'actionable': return 'bg-purple-500/5'
    default:          return ''
  }
})

// Surfaces *exceptions* to the happy path — failures and pending HITL — as
// inline colored text in the title row. The `× N` count chip + status glyph
// already communicate "how many done" for the normal case; duplicating that
// as "4 done" would clutter the row.
const aggregateExceptionLabel = computed<string>(() => {
  const a = props.group.aggregate
  const parts: string[] = []
  if (a.actionable > 0) parts.push(`${a.actionable} awaiting you`)
  if (a.failed > 0) parts.push(`${a.failed} failed`)
  return parts.join(' · ')
})

// Tool resolution — IterationGroup rollups share the provider/tool cache with
// EquationTraceRow and EquationGraph so the three views read the same tool
// names rather than each decoding raw slugs on its own.
const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()
onMounted(() => {
  fetchProvidersAndTools().catch(() => {})
})

function uniqueOrNull<T>(values: (T | null | undefined)[]): T | null {
  const seen = new Set<T>()
  for (const v of values) {
    if (v == null) continue
    seen.add(v)
    if (seen.size > 1) return null
  }
  return seen.size === 1 ? [...seen][0] : null
}

// The rollup reads as one tool call iff every iteration shares the same
// task/tool metadata; then it mirrors the single-step row's action label and
// runtime pill.
const sharedTaskType = computed<string | null>(() =>
  uniqueOrNull(props.group.iterations.map((it) => it.primary?.task_type ?? null)),
)
const sharedToolId = computed<string | null>(() =>
  uniqueOrNull(props.group.iterations.map((it) => it.primary?.tool_id ?? null)),
)

const resolvedTool = computed(() => {
  const tid = sharedToolId.value
  if (!tid) return null
  return cachedTools.value.find((t) => t.full_tool_id === tid) || null
})

const providerName = computed<string | null>(() => {
  if (resolvedTool.value) return resolvedTool.value.provider_name
  const tid = sharedToolId.value
  if (!tid) return null
  const pid = tid.split(':')[0] || null
  if (!pid) return null
  const p = cachedProviders.value.find((pr) => pr.provider_id === pid)
  return p?.provider_name || pid
})

const providerId = computed<string | null>(() => {
  const tid = sharedToolId.value
  if (!tid) return null
  return tid.split(':')[0] || null
})

const isStimmaCloud = computed(() => providerId.value === STIMMA_CLOUD_PROVIDER_ID)

// Action label for the rolled-up row — "Generate Image" instead of the model
// name. task_type is required at the DSL layer (recipe_dsl.primitives.tool()
// rejects calls without it), so iterations always carry it; sharedTaskType
// is non-null when all iterations agree. Falls back to the catalog name /
// displayName for utility tools and mixed-task rollups.
const titleText = computed<string>(() => {
  const tt = sharedTaskType.value
  if (tt) {
    const label = TASK_TYPE_LABELS[tt]
    if (label && label !== 'Utility') return label
  }
  if (resolvedTool.value) return resolvedTool.value.name
  return props.group.displayName
})

const countPillText = computed<string | null>(() => {
  const total = props.group.aggregate.total
  if (!Number.isFinite(total) || total <= 1) return null
  return `x${total}`
})

// Inline runtime pill — model + provider as low-emphasis sanity-check info.
// Suppressed when the title already echoes the model (e.g. utility tools that
// fell back to the catalog name).
const runtimePill = computed<string | null>(() => {
  if (!runtimeModelLabel.value && !runtimeProviderLabel.value) return null
  return [runtimeModelLabel.value, runtimeProviderLabel.value].filter(Boolean).join(' · ')
})

const runtimeModelLabel = computed<string | null>(() => {
  const model = resolvedTool.value?.name || null
  if (!model || model === titleText.value) return null
  return model
})

const runtimeProviderLabel = computed<string | null>(() => {
  const provider = providerName.value
  if (!provider) return null
  return provider
})

// Aggregate duration shown in the header when all iterations completed and
// at least one reported duration. Wall-clock across the block — iterations
// often run in parallel, so summing per-equation durations would
// double-count overlap.
const totalDurationLabel = computed<string | null>(() => {
  const ms = props.group.totalDurationMs
  if (ms == null) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

// Scale thresholds — tuned to fit 4-col / 8-col grids at the viewport widths
// this recipe view is designed for.
const INLINE_MAX = 12
const COMPACT_MAX = 50
const layoutMode = computed<'inline' | 'compact' | 'summary'>(() => {
  const n = props.group.aggregate.total
  if (n <= INLINE_MAX) return 'inline'
  if (n <= COMPACT_MAX) return 'compact'
  return 'summary'
})

const gridColsClass = computed(() => {
  switch (layoutMode.value) {
    case 'inline':  return 'grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6'
    case 'compact': return 'grid-cols-6 sm:grid-cols-8'
    default:        return 'grid-cols-8'
  }
})

// Keep inline / compact grids in original foreach order so invalidating one
// iteration regenerates in place. Summary mode is the exception: there the
// point is to surface problem / active items first.
const sortedIterations = computed<GroupedIteration[]>(() => {
  if (layoutMode.value !== 'summary') return props.group.iterations

  const weight = (s: string, actionable: boolean): number => {
    if (actionable) return 0
    switch (s) {
      case 'failed':    return 1
      case 'computing': return 2
      case 'awaiting_input': return 3
      case 'completed': return 4
      case 'skipped':   return 5
      default:          return 6
    }
  }
  const indexed = props.group.iterations.map((it, i) => ({ it, i }))
  indexed.sort((a, b) => {
    const w = weight(a.it.status, a.it.isActionable) - weight(b.it.status, b.it.isActionable)
    if (w !== 0) return w
    return a.i - b.i
  })
  return indexed.map((x) => x.it)
})

// Summary-mode preview: up to 16 "needs attention" iterations surfaced
// inline. If there's nothing to attend to, this is empty and the ribbon
// + "show all" button is all you see.
const previewIterations = computed<GroupedIteration[]>(() => {
  const priority = props.group.iterations.filter(
    (it) => it.isActionable || it.hasError || it.status === 'computing',
  )
  return priority.slice(0, 16)
})

// Collapsed-header previews: up to 5 completed iteration thumbnails so a
// collapsed group shows what is done without rendering placeholder cells for
// in-progress iterations. Running state is already conveyed by the row status
// and aggregate counts on the right.
interface HeaderThumb { key: string; mediaId: number }
const HEADER_THUMB_LIMIT = 5
const headerThumbs = computed<HeaderThumb[]>(() => {
  return sortedIterations.value
    .map((it) => {
      const mid = it.primary?.result_media_ids?.[0]
      if (typeof mid !== 'number') return null
      return { key: it.wrapperKey, mediaId: mid }
    })
    .filter((thumb): thumb is HeaderThumb => thumb !== null)
    .slice(0, HEADER_THUMB_LIMIT)
})

function ribbonCellClass(it: GroupedIteration): string {
  if (it.isActionable) return 'bg-purple-400'
  switch (it.status) {
    case 'failed':    return 'bg-red-400'
    case 'computing': return 'bg-blue-400 animate-pulse'
    case 'completed': return 'bg-green-400'
    case 'skipped':   return 'bg-content-muted/50'
    default:          return 'bg-white/15'
  }
}

function openIteration(it: GroupedIteration) {
  if (it.status === 'computing') return
  openedIteration.value = it
}
</script>
