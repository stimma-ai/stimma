<template>
  <!-- Row analogue of IterationCard: same status/border treatment, same
       open / regenerate affordances, but laid out as a full-width row
       so multi-line text content reads cleanly instead of being
       crammed into a square tile. Used when an IterationGroup is
       text-shaped (e.g. an llm() loop returning structured prompts).
       Media iterations stay on IterationCard — the tile + thumbnail
       grid is the right read for image grids. -->
  <div
    class="relative rounded-md border overflow-hidden transition group/iteration-row"
    :class="[rootClass, isRunning ? 'cursor-default' : 'cursor-pointer', isEchoed ? 'ring-2 ring-blue-500/60' : '']"
    :title="cardTitle"
    :role="isRunning ? undefined : 'button'"
    :tabindex="isRunning ? undefined : 0"
    @click="handleOpen"
    @keydown.enter.prevent="handleOpen"
    @keydown.space.prevent="handleOpen"
  >
    <div class="flex items-stretch" :class="bodyBgClass">
      <!-- Left rail: status glyph. Same icon family as the placeholder
           tile in IterationCard so the two layouts read consistently. -->
      <div
        class="flex-shrink-0 w-7 flex items-start justify-center pt-2 border-r border-edge-subtle"
      >
        <template v-if="iteration.status === 'computing'">
          <div class="w-3.5 h-3.5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        </template>
        <svg
          v-else-if="iteration.status === 'failed'"
          class="w-4 h-4 text-red-400"
          fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <svg
          v-else-if="iteration.status === 'completed'"
          class="w-4 h-4 text-green-500"
          fill="currentColor" viewBox="0 0 24 24"
        >
          <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
        </svg>
        <svg
          v-else-if="iteration.status === 'awaiting_input'"
          class="w-4 h-4 text-purple-400"
          fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.5 20.25a7.5 7.5 0 0115 0v.75H4.5v-.75z" />
        </svg>
        <span v-else class="w-2 h-2 mt-1.5 rounded-full border border-content-muted/40" />
      </div>

      <!-- Body: content + iteration index marker on top. -->
      <div class="flex-1 min-w-0 px-3 py-2">
        <div
          v-if="iteration.status === 'completed' || iteration.status === 'awaiting_input'"
        >
          <RecipeResultPreview
            :value="iteration.primary?.result"
            :render-markdown="renderMarkdown"
          />
        </div>
        <div
          v-else
          class="text-[12px] text-content-muted"
        >{{ statusText }}</div>
      </div>

      <!-- Right rail: index pip, duration, hover actions. The pip lets
           the user track "iteration #3" across the row stack the same
           way the corner badge does on tiles. -->
      <div
        class="flex-shrink-0 flex items-start gap-1.5 pr-2 pt-1.5"
      >
        <span
          v-if="iterIndexLabel"
          class="text-[10px] tabular-nums text-content-muted/80 mt-0.5"
        >#{{ iterIndexLabel }}</span>
        <span
          v-if="durationLabel"
          class="text-[10px] tabular-nums text-content-muted mt-0.5"
        >{{ durationLabel }}</span>
        <button
          v-if="invalidateKey"
          type="button"
          class="opacity-0 group-hover/iteration-row:opacity-100 text-sm w-6 h-6 flex items-center justify-center rounded bg-overlay-subtle text-content-muted hover:text-content hover:bg-overlay-hover transition-opacity"
          title="Re-run this iteration"
          @click.stop="$emit('invalidate', invalidateKey)"
        >↻</button>
      </div>

      <!-- Reference-in-chat button: top-right corner mirroring the
           tile placement. -->
      <RecipeRefButton
        v-if="iterRefKey"
        :ref-key="iterRefKey"
        kind="iteration"
        :label="iterLabel"
        :breadcrumb="iterBreadcrumb"
        variant="tile"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RecipeResultPreview from './RecipeResultPreview.vue'
import RecipeRefButton from './RecipeRefButton.vue'
import type { GroupedIteration } from '../../composables/useRecipeGrouping'
import { useRecipeReferences, injectRecipeChatIdRef } from '../../composables/useRecipeReferences'
import { shouldShowEquationDuration } from '../../utils/equationDuration'
import { parseRecipeError } from '../../utils/recipeErrors'

interface Props {
  iteration: GroupedIteration
  renderMarkdown?: boolean
}
const props = withDefaults(defineProps<Props>(), { renderMarkdown: false })
const emit = defineEmits<{
  (e: 'open', iteration: GroupedIteration): void
  (e: 'invalidate', equationKey: string): void
}>()

const isRunning = computed<boolean>(() => props.iteration.status === 'computing')

const recipeRefs = useRecipeReferences(injectRecipeChatIdRef())
const iterRefKey = computed<string | null>(() => {
  const w = props.iteration.wrapperKey
  return w ? `iter:${w}` : null
})
const iterLabel = computed<string>(() => {
  const idx = props.iteration.iterKey
  const prim = props.iteration.primary?.display_name?.trim()
  if (prim) return `${prim} #${idx}`
  return `Iteration #${idx}`
})
const iterBreadcrumb = computed<string>(() => {
  const p = props.iteration.primary?.phase_path || []
  return p.length > 0 ? p[p.length - 1] : ''
})
const isEchoed = computed<boolean>(() => {
  const hov = recipeRefs.hoveredRefKey.value
  return !!hov && hov === iterRefKey.value
})

const cardTitle = computed<string>(() => {
  if (isRunning.value) return 'Running — details available after it finishes'
  if (props.iteration.hasError) return failedMessage.value || 'Failed — show details'
  return 'Show details'
})

function handleOpen() {
  if (isRunning.value) return
  emit('open', props.iteration)
}

const invalidateKey = computed<string | null>(() => {
  return props.iteration.primary?.equation_key ?? props.iteration.wrapperKey ?? null
})

const iterIndexLabel = computed<string>(() => props.iteration.iterKey)
const failedEquation = computed(() =>
  props.iteration.equations.find((eq) => eq.status === 'failed' && eq.error)
  || (props.iteration.wrapper.status === 'failed' ? props.iteration.wrapper : null)
  || props.iteration.equations.find((eq) => eq.status === 'failed')
  || null,
)
const failedMessage = computed<string>(() => {
  const parsed = parseRecipeError(failedEquation.value?.error)
  return parsed?.message || ''
})

const statusText = computed<string>(() => {
  switch (props.iteration.status) {
    case 'computing': return 'Generating…'
    case 'failed':    return failedMessage.value || 'Failed'
    case 'pending': {
      switch (props.iteration.blockReason) {
        case 'human': return 'Waiting on approval upstream'
        case 'error': return 'Upstream failed'
        case 'tool':  return 'Waiting for the tool provider'
        case 'cap':   return 'Queued — waiting for an open slot'
        default:      return 'Waiting on upstream work'
      }
    }
    default: return ''
  }
})

const durationLabel = computed<string | null>(() => {
  const eq = props.iteration.primary
  if (!eq || eq.status !== 'completed') return null
  if (!shouldShowEquationDuration(eq.equation_type)) return null
  const ms = typeof eq.compute_duration_ms === 'number'
    && Number.isFinite(eq.compute_duration_ms)
    && eq.compute_duration_ms >= 0
    ? eq.compute_duration_ms
    : eq.execution_duration_ms
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

// Background tint mirrors the tile placeholder's reason-specific
// shading so a row stack reads with the same color vocabulary as a
// tile grid (purple = waiting on you, red = failed, etc.).
const bodyBgClass = computed<string>(() => {
  const status = props.iteration.status
  if (status === 'failed') return 'bg-red-500/5'
  if (status === 'awaiting_input') return 'bg-purple-500/5'
  if (status === 'computing') return 'bg-blue-500/5'
  if (status === 'pending') {
    switch (props.iteration.blockReason) {
      case 'human': return 'bg-purple-500/[0.04]'
      case 'error': return 'bg-red-500/[0.04]'
      case 'tool':  return 'bg-amber-500/[0.04]'
      case 'cap':   return 'bg-blue-500/[0.04]'
      default:      return ''
    }
  }
  return ''
})

const rootClass = computed(() => {
  const base = 'border-edge-subtle hover:border-content-muted/60'
  if (props.iteration.isActionable) return 'border-purple-500/50 ring-1 ring-purple-500/30'
  if (props.iteration.hasError) return 'border-red-500/50'
  if (props.iteration.status === 'computing') return 'border-blue-500/40'
  if (props.iteration.status === 'awaiting_input') return 'border-purple-500/50 ring-1 ring-purple-500/30'
  if (props.iteration.status === 'pending') {
    switch (props.iteration.blockReason) {
      case 'human': return 'border-purple-500/25 hover:border-purple-500/40'
      case 'error': return 'border-red-500/25 hover:border-red-500/40'
      case 'tool':  return 'border-amber-500/30 hover:border-amber-500/45'
      case 'cap':   return 'border-blue-500/25 hover:border-blue-500/40'
      default:      return base
    }
  }
  return base
})
</script>
