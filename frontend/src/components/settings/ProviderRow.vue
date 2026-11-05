<script setup lang="ts">
// The settings list-row grammar for providers and services: icon, name and
// description on the left, ONE status or quiet verb on the right, all rows
// sharing one right-hand column. Rows are whitespace-separated (hairline
// budget, DESIGN.md §1.3); the whole row is the tap target, so there is no
// chevron. A verb is the shared ghost action (a quiet fill, medium weight,
// primary text) and a status is plain tertiary text with its dot, both inset
// the same amount so they end on one edge. The sanctioned Stimma gradient CTA goes in the `cta` slot. Three
// explicit columns (icon, text, trailing), centred on the row, and on compact
// a fixed row height (room for a two-line description), so rows keep one pitch
// whether a description wraps or not.
withDefaults(defineProps<{
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
      <span v-if="error" class="mt-1 line-clamp-2 block text-xs text-red-400">{{ error }}</span>
    </span>
    <span v-if="$slots.cta || verb || $slots.status" class="flex w-28 shrink-0 items-center justify-end text-xs compact:w-24">
      <slot v-if="$slots.cta" name="cta" />
      <span v-else-if="verb" class="whitespace-nowrap rounded-md bg-overlay-subtle px-3 py-1.5 font-medium text-content transition-colors duration-150 group-hover:bg-overlay-light">{{ verb }}</span>
      <span v-else class="inline-flex items-center gap-1.5 whitespace-nowrap px-3 py-1.5" :class="statusClass"><slot name="status" /></span>
    </span>
  </button>
</template>
