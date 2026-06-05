<template>
  <div
    class="relative rounded-md border overflow-hidden transition group/iteration-card"
    :class="[rootClass, isRunning ? 'cursor-default' : 'cursor-pointer', isEchoed ? 'ring-2 ring-blue-500/60' : '']"
    :title="cardTitle"
    :role="isRunning ? undefined : 'button'"
    :tabindex="isRunning ? undefined : 0"
    @click="handleOpen"
    @keydown.enter.prevent="handleOpen"
    @keydown.space.prevent="handleOpen"
  >
    <!-- Primary media tile. Images/videos use `contain` so faces and subjects
         aren't cropped by the square frame; grids/sets use the standard
         library-browser treatment (square + cover on their pre-computed
         composite thumbnail). -->
    <template v-if="primaryMediaId">
      <RecipeMediaTile
        :media-id="primaryMediaId"
        :media-ids="primaryMediaIds"
        :thumbnail="true"
        :thumbnail-size="size === 'full' ? 256 : 160"
        :contain="!isCompositePrimary"
        :container-class="tileAspectClass"
      />
    </template>

    <!-- No-media states: colored placeholder conveying status. Pending tiles
         differentiate by *why* they're pending (block reason) — sitting on
         the concurrency cap reads very differently from blocked behind a
         HITL waiting on a human, even though the scheduler calls both
         "pending". -->
    <div
      v-else
      class="flex items-center justify-center"
      :class="[tileAspectClass, placeholderBgClass]"
      :title="placeholderTitle"
    >
      <template v-if="iteration.status === 'computing'">
        <div class="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
      </template>
      <template v-else-if="iteration.status === 'failed'">
        <svg class="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </template>
      <template v-else-if="iteration.status === 'awaiting_input'">
        <!-- Person glyph in solid purple — this iteration itself is the
             one waiting on the human. Border treatment from rootClass
             handles the framing; this is the in-tile signal. -->
        <svg class="w-5 h-5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.5 20.25a7.5 7.5 0 0115 0v.75H4.5v-.75z" />
        </svg>
      </template>
      <template v-else-if="iteration.status === 'pending'">
        <!-- Block-reason-specific glyph. Falls through to the default
             clock for vanilla "waiting on upstream work". -->
        <svg
          v-if="iteration.blockReason === 'human'"
          class="w-5 h-5 text-purple-400/70"
          fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.5 20.25a7.5 7.5 0 0115 0v.75H4.5v-.75z" />
        </svg>
        <svg
          v-else-if="iteration.blockReason === 'error'"
          class="w-5 h-5 text-red-400/70"
          fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.008v.008H12v-.008z" />
        </svg>
        <svg
          v-else-if="iteration.blockReason === 'tool'"
          class="w-5 h-5 text-amber-400/80"
          fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 3l18 18M2.25 12c0-4.97 4.03-9 9-9 2.46 0 4.69.99 6.31 2.59M21.75 12a9 9 0 01-9 9 8.96 8.96 0 01-6.31-2.59M8.25 12a3.75 3.75 0 015.96-3.04m1.54 1.54A3.75 3.75 0 0115.75 12" />
        </svg>
        <svg
          v-else-if="iteration.blockReason === 'cap'"
          class="w-4 h-4 text-blue-400/70"
          fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
        >
          <!-- Hourglass: deps satisfied, ready to run, slot-capped. -->
          <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25c0 1.5 5.25 3.75 5.25 6.75s-5.25 5.25-5.25 6.75V21m10.5-18v2.25c0 1.5-5.25 3.75-5.25 6.75s5.25 5.25 5.25 6.75V21M5.25 3h13.5M5.25 21h13.5" />
        </svg>
        <svg
          v-else
          class="w-4 h-4 text-content-muted/70"
          fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
        >
          <!-- Default 'compute': vanilla clock, the boring "waiting on upstream work" case. -->
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </template>
      <template v-else>
        <div
          class="px-2 text-[11px] text-content-muted text-center line-clamp-3"
        >{{ textPreview || '—' }}</div>
      </template>
    </div>

    <div
      v-if="durationLabel"
      class="absolute bottom-1 left-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white tabular-nums"
    >{{ durationLabel }}</div>

    <button
      v-if="!isRunning"
      type="button"
      class="absolute bottom-1 right-1 z-10 h-6 w-6 flex items-center justify-center rounded bg-black/60 text-white/85 opacity-0 transition-all hover:bg-blue-500/80 hover:text-white group-hover/iteration-card:opacity-100"
      title="Show iteration details"
      @click.stop="$emit('open', iteration)"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
      </svg>
    </button>

    <button
      v-if="invalidateKey"
      type="button"
      class="absolute top-1 right-1 opacity-0 group-hover/iteration-card:opacity-100 text-sm w-6 h-6 flex items-center justify-center rounded bg-black/55 text-white/85 hover:bg-black/75 transition-opacity"
      title="Re-run this iteration"
      @click.stop="$emit('invalidate', invalidateKey)"
    >↻</button>

    <!-- Reference-in-chat button: top-left corner, hover-revealed. Filled
         blue (and stays visible) once the iteration is pinned to the chat
         context tray. -->
    <RecipeRefButton
      v-if="iterRefKey"
      :ref-key="iterRefKey"
      kind="iteration"
      :label="iterLabel"
      :breadcrumb="iterBreadcrumb"
      variant="tile"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RecipeMediaTile from './RecipeMediaTile.vue'
import RecipeRefButton from './RecipeRefButton.vue'
import type { GroupedIteration } from '../../composables/useRecipeGrouping'
import { useRecipeReferences, injectRecipeChatIdRef } from '../../composables/useRecipeReferences'
import { shouldShowEquationDuration } from '../../utils/equationDuration'
import { parseRecipeError } from '../../utils/recipeErrors'

interface Props {
  iteration: GroupedIteration
  size?: 'full' | 'compact'
}
const props = withDefaults(defineProps<Props>(), { size: 'full' })
const emit = defineEmits<{
  (e: 'open', iteration: GroupedIteration): void
  (e: 'invalidate', equationKey: string): void
}>()

const isRunning = computed<boolean>(() => props.iteration.status === 'computing')

// Reference-in-chat wiring. refKey is the iteration wrapper prefixed with
// `iter:` so it doesn't collide with equation_key namespace. Echo fires when
// the user hovers the matching chip in the context tray.
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
  if (!hov) return false
  return hov === iterRefKey.value
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

// Prefer the iteration's primary equation (the media producer); fall back to
// the wrapper so callback-build-time failures still retry.
const invalidateKey = computed<string | null>(() => {
  const primaryKey = props.iteration.primary?.equation_key
  if (primaryKey) return primaryKey
  return props.iteration.wrapperKey || null
})

const primaryMediaIds = computed<number[]>(() => props.iteration.primary?.result_media_ids ?? [])
const primaryMediaId = computed<number | null>(() => primaryMediaIds.value[0] ?? null)
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

// Composite media (grid / set) have a pre-computed square composite thumbnail
// and should render with the standard library-browser treatment (cover).
// Everything else (images, videos) renders with contain so the full frame is
// visible without cropping.
const isCompositePrimary = computed<boolean>(() => {
  const t = props.iteration.primary?.equation_type
  return t === 'create_grid' || t === 'create_set'
})

const tileAspectClass = computed(() => 'aspect-square w-full')

// Background tint for no-media states — keeps the card meaningful at a glance.
// Pending tiles get a faint reason-specific tint so the icon isn't carrying
// the full signal alone.
const placeholderBgClass = computed(() => {
  const status = props.iteration.status
  if (status === 'failed') return 'bg-red-500/10'
  if (status === 'awaiting_input') return 'bg-purple-500/10'
  if (status === 'completed') return 'bg-overlay-subtle/50'
  if (status === 'pending') {
    switch (props.iteration.blockReason) {
      case 'human': return 'bg-purple-500/[0.06]'
      case 'error': return 'bg-red-500/[0.06]'
      case 'tool':  return 'bg-amber-500/[0.06]'
      case 'cap':   return 'bg-blue-500/[0.06]'
      default:      return 'bg-overlay-subtle/30'
    }
  }
  return 'bg-overlay-subtle/30'
})

// Border / ring color. Actionable (this node awaiting human) wins because
// it's the only state that demands user attention; downstream-blocked
// tiles use a desaturated form of the same color family so they read as
// related-but-not-actionable.
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

// Tooltip on the placeholder so the reason is discoverable on hover.
// (The icon family is the at-a-glance signal; the tooltip is the
// "what does this mean again" backup.)
const placeholderTitle = computed<string | undefined>(() => {
  const status = props.iteration.status
  if (status === 'computing') return 'Running…'
  if (status === 'failed') return failedMessage.value || 'Failed'
  if (status === 'awaiting_input') return 'Awaiting your input'
  if (status === 'pending') {
    switch (props.iteration.blockReason) {
      case 'human': return 'Waiting on approval upstream'
      case 'error': return 'Upstream failed — won’t run until that’s resolved'
      case 'tool':  return 'Waiting for the tool provider to come online'
      case 'cap':   return 'Ready — waiting for an open slot'
      case 'compute': return 'Waiting on upstream work'
      default:      return 'Pending'
    }
  }
  return undefined
})

const durationLabel = computed<string | null>(() => {
  const eq = props.iteration.primary
  if (!eq || eq.status !== 'completed') return null
  if (!shouldShowEquationDuration(eq.equation_type)) return null
  // Prefer compute_duration_ms (pure tool time from media generation_metadata)
  // over execution_duration_ms (wall-clock including tool-side queue wait).
  // Per-iteration "how long did this image take to generate" reads the tool
  // time; aggregates still use wall-clock for the user-waited envelope.
  const ms = typeof eq.compute_duration_ms === 'number' && Number.isFinite(eq.compute_duration_ms) && eq.compute_duration_ms >= 0
    ? eq.compute_duration_ms
    : eq.execution_duration_ms
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

// Short one-line preview of the primary equation's text result when there's
// no media — helps the user spot which iteration is which.
const textPreview = computed<string>(() => {
  const r = props.iteration.primary?.result
  if (typeof r === 'string') return r.trim().slice(0, 80)
  if (r == null) return ''
  try { return JSON.stringify(r).slice(0, 80) } catch { return String(r) }
})

</script>
