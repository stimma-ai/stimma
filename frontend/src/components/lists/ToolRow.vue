<script setup lang="ts">
// One row of the tools catalog, one model per row on one left edge, with the
// same pitch whatever it carries.
//
//   - a single tool (no `variants`): the whole row is the link. Its name, an
//     optional label and a tag, with a hover tint (a press tint on touch).
//   - a model with variants: the name is plain text and its variants follow
//     it on the same row (wrapping to a second line when narrow) as small
//     neutral chips. Each chip is the link to one tool; a chip is 44px tall on
//     touch.
//
// Capability facts sit on one quiet line under the name in both cases, then
// the description when there is one. The section heading above carries the
// task glyph, so rows carry none. Text starts on the column the section
// heading's text starts on. Listeners and classes fall through to the root.
import { EllipsisVerticalIcon } from '@heroicons/vue/24/outline'

interface Fact { text: string; cloud?: boolean }
interface Variant {
  key: string
  label: string
  tag?: string
  /** Quiet tooltip: the facts that tell this variant from its siblings. */
  title?: string
  unavailable?: boolean
  menu?: boolean
}

withDefaults(defineProps<{
  name: string
  /** A single tool's lone variant label. */
  label?: string
  /** Last-resort tell for variants that share name and facts (a tool id). */
  tag?: string
  facts?: Fact[]
  hidden?: number
  factsTitle?: string
  price?: string
  description?: string
  /** Variants of this model, shown as chips after the name. */
  variants?: Variant[]
  /** The row has its own options menu (user tools). */
  menu?: boolean
}>(), { label: '', tag: '', facts: () => [], hidden: 0, factsTitle: '', price: '', description: '', variants: () => [], menu: false })

defineEmits<{
  (e: 'menu', event: MouseEvent, key?: string): void
  (e: 'open', key: string): void
}>()
</script>

<template>
  <div
    class="group relative -mx-2 flex min-h-9 items-center gap-3 rounded-md py-1.5 pl-8 pr-2 transition-colors duration-150"
    :class="[
      variants.length ? '' : 'cursor-pointer hover:bg-overlay-subtle active:bg-overlay-light coarse:min-h-11',
      menu ? 'coarse:pr-12' : '',
    ]"
  >
    <div class="min-w-0 flex-1" :title="variants.length ? undefined : name">
      <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <span class="max-w-full flex-none truncate text-sm font-medium leading-5 text-content" :title="name">{{ name }}</span>
        <template v-if="variants.length">
          <button
            v-for="v in variants"
            :key="v.key"
            type="button"
            class="inline-flex h-7 max-w-full items-center gap-1.5 rounded-md bg-overlay-subtle px-2.5 text-xs leading-5 text-content-secondary transition-colors hover:bg-overlay-light hover:text-content active:bg-overlay-light coarse:h-11 coarse:px-3.5"
            :class="v.unavailable ? 'pointer-events-none opacity-40' : ''"
            :title="v.title || undefined"
            :aria-label="`${name} ${v.label}`"
            @click="$emit('open', v.key)"
            @contextmenu.prevent="v.menu ? $emit('menu', $event, v.key) : null"
          >
            <span class="truncate">{{ v.label }}</span>
            <span v-if="v.tag" class="flex-none font-mono text-[11px] text-content-muted">{{ v.tag }}</span>
          </button>
        </template>
        <template v-else>
          <span v-if="label" class="max-w-full flex-none truncate text-sm leading-5 text-content-secondary">{{ label }}</span>
          <span v-if="tag" class="flex-none font-mono text-[11px] leading-5 text-content-muted">{{ tag }}</span>
        </template>
      </div>
      <p
        v-if="facts.length || hidden > 0"
        class="flex min-w-0 items-baseline gap-x-1.5 text-xs leading-5 text-content-tertiary"
        :title="factsTitle"
      >
        <template v-for="(fact, i) in facts" :key="fact.text">
          <span v-if="i > 0" class="shrink-0" aria-hidden="true">·</span>
          <span class="min-w-0 truncate whitespace-nowrap" :class="fact.cloud ? 'stimma-cloud-text font-medium' : ''">{{ fact.text }}</span>
        </template>
        <span v-if="hidden > 0" class="shrink-0 font-mono tabular-nums">+{{ hidden }}</span>
      </p>
      <p v-if="description" class="truncate text-xs leading-5 text-content-secondary">{{ description }}</p>
    </div>

    <span
      v-if="price"
      class="flex-none font-mono text-[11px] leading-5 tabular-nums text-content-tertiary"
      :class="menu ? 'group-hover:opacity-0 coarse:group-hover:opacity-100' : ''"
    >{{ price }}</span>

    <button
      v-if="menu && !variants.length"
      type="button"
      class="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 group-hover:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100"
      title="Tool options"
      @click.stop="$emit('menu', $event)"
    >
      <EllipsisVerticalIcon class="h-icon-nav w-icon-nav" />
    </button>
  </div>
</template>
