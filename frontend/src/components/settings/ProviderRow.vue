<script setup lang="ts">
import { computed, useSlots } from 'vue'
// The settings list-row grammar for providers and services: icon, name and
// description on the left; on the right the same structure in every state, a
// quiet secondary status (when there is one) and ONE action in a fixed column
// (the verb or the sign-in CTA when not connected, "Manage" once connected).
// Rows are whitespace-separated (hairline budget, DESIGN.md 1.3); the whole row
// is the tap target, so there is no chevron. The sanctioned Stimma gradient CTA
// goes in the `cta` slot. Three explicit columns (icon, text, trailing),
// centred on the row, and on compact a fixed row height (room for a two-line
// description), so rows keep one pitch whether a description wraps or not.
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
  /** Leading icon is the primary action colour (the "Add" row). */
  accentIcon?: boolean
}>(), { descriptionClass: 'text-content-tertiary', statusClass: 'text-content-tertiary' })

// A status shows only when the row is not wearing a verb or the sign-in CTA.
const showStatus = computed(() => !!slots.status && !props.verb && !slots.cta)
</script>

<template>
  <button
    type="button"
    class="group -mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-md px-2 py-3 text-left transition-colors hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 ring-accent/60 compact:min-h-[72px]"
  >
    <span class="flex h-9 w-9 shrink-0 items-center justify-center" :class="accentIcon ? 'text-accent-hi' : 'text-content-secondary'">
      <slot name="icon" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="block truncate text-[13px] compact:text-[15px]" :class="accentIcon ? 'font-medium text-accent-hi' : dimmed ? 'text-content-muted' : 'text-content'"><slot name="name">{{ name }}</slot></span>
      <span v-if="description || $slots.description" class="mt-0.5 line-clamp-2 block text-xs" :class="descriptionClass"><slot name="description">{{ description }}</slot></span>
      <!-- On a phone the status moves under the description so the right-hand
           column is the action alone. -->
      <span v-if="showStatus" class="mt-0.5 hidden items-center gap-1.5 text-xs compact:flex" :class="statusClass"><slot name="status" /></span>
      <span v-if="error" class="mt-1 line-clamp-2 block text-xs text-red-400">{{ error }}</span>
    </span>
    <!-- One trailing structure for every state: the status (when there is
         one) as quiet secondary text, then ONE action in a fixed column: the
         call to action or verb when not connected, "Manage" once it is. -->
    <span v-if="$slots.cta || verb || $slots.status" class="flex shrink-0 items-center justify-end gap-3 text-xs">
      <span v-if="showStatus" class="inline-flex items-center gap-1.5 whitespace-nowrap compact:hidden" :class="statusClass"><slot name="status" /></span>
      <span class="flex w-24 items-center justify-end compact:w-20">
        <slot v-if="$slots.cta" name="cta" />
        <span v-else-if="verb" class="whitespace-nowrap rounded-md bg-overlay-subtle px-3 py-1.5 font-medium text-content transition-colors duration-150 group-hover:bg-overlay-light">{{ verb }}</span>
        <span v-else class="whitespace-nowrap rounded-md px-3 py-1.5 font-medium text-content-secondary transition-colors duration-150 group-hover:bg-overlay-light group-hover:text-content">Manage</span>
      </span>
    </span>
  </button>
</template>
