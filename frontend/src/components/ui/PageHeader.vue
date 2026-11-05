<script setup lang="ts">
// The one page header (DESIGN.md §2 PageHeader): one height, one title style
// (18px display), one fill, one left inset (--page-margin) on every desktop
// page. `tier` is accepted for existing callers and changes nothing.
// One slot order: title, meta, actions, menu.
// The menu slot holds the overflow button (ui/OverflowButton.vue), last on the
// right. Phones use CompactHeader instead; callers hide this with `compact:hidden`.
import { pageHeaderClass, pageHeaderTitleClass } from './pageHeader'

withDefaults(defineProps<{
  tier?: 'standard' | 'compact'
  /** Render the bottom hairline. Off when a second row of the same header follows. */
  rule?: boolean
}>(), { tier: 'standard', rule: true })
</script>

<template>
  <header :class="pageHeaderClass(tier, rule)" :data-page-header="tier">
    <div class="flex min-w-0 flex-1 items-center gap-3">
      <h1 :class="pageHeaderTitleClass(tier)"><slot name="title" /></h1>
      <div v-if="$slots.meta" class="flex min-w-0 items-center gap-2 text-xs text-content-tertiary"><slot name="meta" /></div>
    </div>
    <div v-if="$slots.actions" class="flex flex-none items-center gap-2"><slot name="actions" /></div>
    <slot name="menu" />
  </header>
</template>
