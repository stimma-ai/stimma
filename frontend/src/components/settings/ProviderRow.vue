<script setup lang="ts">
import { computed, nextTick, onMounted, onUpdated, ref, useSlots } from 'vue'
// The settings list-row grammar for providers and services: icon, name and
// description on the left; on the right the same structure in every state, a
// quiet secondary status (when there is one) and ONE action in a fixed column
// (the verb or the sign-in CTA when not connected, "Manage" once connected).
// Rows are hairline-separated by their list (every setting is a hairline row,
// DESIGN.md); the whole row is the tap target, so there is no chevron. The sanctioned Stimma gradient CTA
// goes in the `cta` slot. Three explicit columns (icon, text, trailing),
// centred on the row, and on compact a grid: the name, the status and the action share the first line
// (the action in one fixed-width column) and the description runs the full row
// beneath, on a single line.
const slots = useSlots()
const props = withDefaults(defineProps<{
  name: string
  /** Quiet one-line-or-two description under the name. */
  description?: string
  descriptionClass?: string
  /** Red detail line under the description. */
  error?: string
  /** Name reads muted (disabled provider). */
  dimmed?: boolean
  /** Ghost verb on the right ("Configure", "Sign in"). Wins over the status slot. */
  verb?: string
  /** Colour class for the status slot's text. */
  statusClass?: string
  /** The "Add" row: a medium-weight label, tertiary in the action hierarchy (neutral, never teal text). */
  accentIcon?: boolean
}>(), { descriptionClass: 'text-content-tertiary', statusClass: 'text-content-tertiary' })

// A status shows only when the row is not wearing a verb or the sign-in CTA:
// beside the action on desktop, on the second line on compact.
// Configure, Sign in and Manage are one secondary action (DESIGN.md 2, action
// roles); only the Stimma account's gradient `cta` differs.
const actionClass = 'whitespace-nowrap rounded-md bg-surface-raised px-3 py-1.5 font-medium text-content transition-colors duration-150 group-hover:bg-surface-hover'
const showStatus = computed(() => !!slots.status && !props.verb && !slots.cta)
const hasTrailing = computed(() => !!(slots.cta || props.verb || slots.status))

// Logo normalisation: every provider mark is drawn in one 22px slot and its SVG
// viewBox is tightened to the glyph's own bounds, so a mark with generous
// built-in padding reads at the same size as one that fills its canvas. Stroke
// icons (the endpoint chip, the Add plus) are left alone.
const iconSlot = ref<HTMLElement | null>(null)
function fitLogos() {
  iconSlot.value?.querySelectorAll('svg').forEach((svg) => {
    if (svg.dataset.fitted || svg.getAttribute('fill') === 'none') return
    try {
      const box = svg.getBBox()
      if (!box.width || !box.height) return
      const side = Math.max(box.width, box.height)
      const x = box.x + box.width / 2 - side / 2
      const y = box.y + box.height / 2 - side / 2
      svg.setAttribute('viewBox', `${x} ${y} ${side} ${side}`)
      svg.removeAttribute('width')
      svg.removeAttribute('height')
      svg.dataset.fitted = '1'
    } catch { /* not rendered yet; the next update retries */ }
  })
}
onMounted(() => nextTick(fitLogos))
onUpdated(() => nextTick(fitLogos))
</script>

<template>
  <button
    type="button"
    class="group -mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-md px-2 py-3 text-left transition-colors hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 ring-accent/60 compact:grid compact:min-h-14 compact:grid-cols-[2.25rem_minmax(0,1fr)_auto_6rem] compact:gap-x-3 compact:gap-y-0.5 compact:py-2.5"
  >
    <span ref="iconSlot" class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary compact:col-start-1 compact:row-start-1 [&>div]:!h-[22px] [&>div]:!w-[22px] [&>span]:!h-[22px] [&>span]:!w-[22px]">
      <slot name="icon" />
    </span>
    <!-- On a phone this wrapper dissolves into the grid: the name sits on the
         first line with the status and the action, and the description takes
         the whole row beneath, never narrowed by the status. -->
    <span class="min-w-0 flex-1 compact:contents">
      <span class="block truncate text-[13px] compact:col-start-2 compact:row-start-1 compact:text-[15px]" :class="[hasTrailing ? '' : 'compact:col-span-3', accentIcon ? 'font-medium text-content' : dimmed ? 'text-content-muted' : 'text-content']"><slot name="name">{{ name }}</slot></span>
      <span v-if="description || $slots.description || error" class="block min-w-0 compact:col-span-3 compact:col-start-2 compact:row-start-2">
        <span v-if="description || $slots.description" class="mt-0.5 line-clamp-2 block min-w-0 text-xs compact:mt-0 compact:line-clamp-1" :class="descriptionClass"><slot name="description">{{ description }}</slot></span>
        <span v-if="error" class="mt-1 line-clamp-2 block text-xs text-red-400">{{ error }}</span>
      </span>
    </span>
    <!-- One trailing structure for every state: the status (when there is
         one) as quiet secondary text immediately left of ONE action in a fixed
         column: the call to action or verb when not connected, "Manage" once
         it is. On a phone both join the name's line of the grid. -->
    <span v-if="$slots.cta || verb || $slots.status" class="flex shrink-0 items-center justify-end gap-3 text-xs compact:contents">
      <span v-if="showStatus" class="inline-flex items-center gap-1.5 whitespace-nowrap compact:col-start-3 compact:row-start-1" :class="statusClass"><slot name="status" /></span>
      <span class="flex w-24 items-center justify-end compact:col-start-4 compact:row-start-1 [&>*]:w-full [&>*]:text-center">
        <slot v-if="$slots.cta" name="cta" />
        <span v-else-if="verb" :class="actionClass">{{ verb }}</span>
        <span v-else :class="actionClass">Manage</span>
      </span>
    </span>
  </button>
</template>
