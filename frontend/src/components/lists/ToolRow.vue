<script setup lang="ts">
// One row of the tools catalog. Two heights only: a one-line row (32px, 44px on
// touch) and a two-line row (52px) for a row that carries a description, or on
// a narrow window one that carries facts. Names are single-line and truncate
// (the full name is the tooltip) so a row never grows past its height.
//
// A row is one of three things:
//   - a family header (`interactive` off): glyph, the family name in the
//     semibold weight, and the facts every variant shares. Not a target, so no
//     hover tint and no chevron.
//   - a variant (`indent` on): the distinguishing label in regular weight,
//     indented one step past the family name, with only the facts that tell it
//     from its siblings.
//   - a single tool: glyph, name, optional label, facts.
//
// Facts sit beside the name they qualify; on a narrow window they drop beneath
// it. Listeners and classes fall through to the root.
import { ChevronRightIcon, EllipsisVerticalIcon } from '@heroicons/vue/24/outline'

interface Fact { text: string; cloud?: boolean }

withDefaults(defineProps<{
  name: string
  /** Distinguishing label of a variant, or a single tool's lone variant. */
  label?: string
  /** Last-resort tell for variants that share name and facts (a tool id). */
  tag?: string
  facts?: Fact[]
  hidden?: number
  factsTitle?: string
  price?: string
  description?: string
  /** Inner SVG path data (outline, 24px grid) for the leading glyph. */
  glyph?: string
  /** A variant row: name starts on the family name's edge, no glyph. */
  indent?: boolean
  /** A tool that opens on click. Off for a family header. */
  interactive?: boolean
  /** The row has its own options menu (user tools). */
  menu?: boolean
}>(), { label: '', tag: '', facts: () => [], hidden: 0, factsTitle: '', price: '', description: '', glyph: '', indent: false, interactive: true, menu: false })

defineEmits<{ (e: 'menu', event: MouseEvent): void }>()
</script>

<template>
  <div
    class="group relative -mx-2 grid grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-x-3 rounded-md pr-2 py-1 transition-colors coarse:min-h-11"
    :class="[
      indent ? 'pl-5' : 'pl-2',
      interactive ? 'cursor-pointer hover:bg-overlay-subtle active:bg-overlay-light' : '',
      description ? 'min-h-[3.25rem]' : facts.length ? 'min-h-8 narrow:min-h-[3.25rem]' : 'min-h-8',
    ]"
  >
    <svg
      v-if="glyph && !indent"
      class="h-icon-nav w-icon-nav text-content-tertiary"
      fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"
    >
      <path stroke-linecap="round" stroke-linejoin="round" :d="glyph" />
    </svg>
    <span v-else aria-hidden="true"></span>

    <div class="min-w-0" :title="name">
      <div class="flex min-w-0 items-baseline gap-x-2 narrow:flex-wrap">
        <span
          v-if="!indent"
          class="min-w-0 max-w-full truncate text-sm leading-5 text-content"
          :class="interactive ? 'font-medium' : 'font-semibold'"
        >{{ name }}</span>
        <span
          v-if="label"
          class="min-w-0 max-w-full truncate text-sm leading-5"
          :class="indent ? 'text-content' : 'text-content-secondary'"
        >{{ label }}</span>
        <span v-if="tag" class="shrink-0 font-mono text-[11px] leading-5 text-content-muted">{{ tag }}</span>
        <span
          v-if="facts.length || hidden > 0"
          class="flex min-w-0 shrink items-baseline gap-x-1.5 text-xs leading-5 text-content-tertiary narrow:w-full"
          :title="factsTitle"
        >
          <template v-for="(fact, i) in facts" :key="fact.text">
            <span v-if="i > 0" class="shrink-0" aria-hidden="true">·</span>
            <span class="min-w-0 truncate whitespace-nowrap" :class="fact.cloud ? 'stimma-cloud-text font-medium' : ''">{{ fact.text }}</span>
          </template>
          <span v-if="hidden > 0" class="shrink-0 font-mono tabular-nums">+{{ hidden }}</span>
        </span>
      </div>
      <p v-if="description" class="truncate text-xs leading-5 text-content-secondary">{{ description }}</p>
    </div>

    <div v-if="interactive || price" class="flex items-center gap-3">
      <span v-if="price" class="font-mono text-[11px] leading-5 tabular-nums text-content-tertiary">{{ price }}</span>
      <ChevronRightIcon
        v-if="interactive"
        class="h-icon-inline w-icon-inline text-content-muted opacity-60 transition-opacity group-hover:opacity-100"
        :class="menu ? 'group-hover:!opacity-0 coarse:!hidden' : ''"
        aria-hidden="true"
      />
    </div>

    <button
      v-if="menu"
      type="button"
      class="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 group-hover:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100"
      title="Tool options"
      @click.stop="$emit('menu', $event)"
    >
      <EllipsisVerticalIcon class="h-icon-nav w-icon-nav" />
    </button>
  </div>
</template>
