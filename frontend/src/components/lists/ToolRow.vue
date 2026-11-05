<script setup lang="ts">
// One row of the tools catalog. Two heights only: a one-line row (32px, 44px on
// touch) and a two-line row (52px) for a row that carries a description. Names
// and facts are single-line and truncate (the full name is the tooltip), facts
// first, so a row never grows past its height at any width.
//
// A row is one of three things:
//   - a family header (`interactive` off): the family name in the semibold
//     weight and the facts every variant shares. Not a target.
//   - a variant (`indent` on): the distinguishing label in regular weight,
//     indented one step past the family name under a hairline rail, with only
//     the facts that tell it from its siblings.
//   - a single tool: name, optional label, facts.
//
// The section heading above carries the task glyph, so rows carry none, and a
// row is plainly a link: it takes a hover tint (a press tint on touch) and no
// chevron. Text starts on the column the section heading's text starts on.
// Listeners and classes fall through to the root.
import { EllipsisVerticalIcon } from '@heroicons/vue/24/outline'

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
  /** A variant row: starts one step past the family name, under the rail. */
  indent?: boolean
  /** A tool that opens on click. Off for a family header. */
  interactive?: boolean
  /** The row has its own options menu (user tools). */
  menu?: boolean
}>(), { label: '', tag: '', facts: () => [], hidden: 0, factsTitle: '', price: '', description: '', indent: false, interactive: true, menu: false })

defineEmits<{ (e: 'menu', event: MouseEvent): void }>()
</script>

<template>
  <div
    class="group relative -mx-2 flex items-center gap-3 rounded-md py-1 pr-2 transition-colors duration-150"
    :class="[
      indent ? 'pl-12' : 'pl-8',
      interactive ? 'cursor-pointer hover:bg-overlay-subtle active:bg-overlay-light coarse:min-h-11' : '',
      indent ? 'before:pointer-events-none before:absolute before:inset-y-0 before:left-8 before:w-px before:bg-edge-subtle' : '',
      description ? 'min-h-[3.25rem]' : 'min-h-8',
      menu ? 'coarse:pr-12' : '',
    ]"
  >
    <div class="min-w-0 flex-1" :title="name">
      <div class="flex min-w-0 items-baseline gap-x-2">
        <span
          v-if="!indent"
          class="max-w-full flex-none truncate text-sm leading-5 text-content"
          :class="interactive ? 'font-medium' : 'font-semibold'"
        >{{ name }}</span>
        <span
          v-if="label"
          class="max-w-full flex-none truncate text-sm leading-5"
          :class="indent ? 'text-content' : 'text-content-secondary'"
        >{{ label }}</span>
        <span v-if="tag" class="flex-none font-mono text-[11px] leading-5 text-content-muted">{{ tag }}</span>
        <span
          v-if="facts.length || hidden > 0"
          class="flex min-w-0 shrink items-baseline gap-x-1.5 text-xs leading-5 text-content-tertiary"
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

    <span
      v-if="price"
      class="flex-none font-mono text-[11px] leading-5 tabular-nums text-content-tertiary"
      :class="menu ? 'group-hover:opacity-0 coarse:group-hover:opacity-100' : ''"
    >{{ price }}</span>

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
