<template>
  <span v-if="rating === 'stars'" class="flex flex-none items-center" role="group" aria-label="Rating" @mouseleave="hover = 0">
    <button
      v-for="n in 5"
      :key="n"
      type="button"
      class="flex items-center justify-center disabled:cursor-default"
      :class="large ? 'h-9 w-9' : 'h-6 w-[18px] coarse:h-9 coarse:w-5'"
      :title="`${n} of 5`"
      :aria-label="`${n} of 5`"
      :aria-pressed="review.stars === n"
      :disabled="sheet.readonly.value"
      @mouseenter="hover = n"
      @click.stop="sheet.setReview(anchor, { stars: review.stars === n ? null : n })"
    >
      <StarIcon class="transition-colors" :class="[large ? 'h-5 w-5' : 'h-3.5 w-3.5', (hover || review.stars || 0) >= n ? 'text-amber-400' : 'text-content-muted/40']" />
    </button>
  </span>
  <span v-else class="flex flex-none items-center" role="group" aria-label="Rating">
    <button
      v-for="thumb in THUMBS"
      :key="thumb.value"
      type="button"
      class="flex items-center justify-center rounded-md transition-colors disabled:cursor-default"
      :class="[
        large ? 'h-9 w-9' : 'h-6 w-6 coarse:h-9 coarse:w-7',
        review.thumb === thumb.value ? thumb.on : 'text-content-muted hover:bg-overlay-subtle hover:text-content',
      ]"
      :title="thumb.title"
      :aria-label="thumb.title"
      :aria-pressed="review.thumb === thumb.value"
      :disabled="sheet.readonly.value"
      @click.stop="sheet.setReview(anchor, { thumb: review.thumb === thumb.value ? null : thumb.value })"
    >
      <component :is="review.thumb === thumb.value ? thumb.solid : thumb.outline" :class="large ? 'h-5 w-5' : 'h-4 w-4'" />
    </button>
  </span>
</template>

<script setup lang="ts">
// The quick rating beside every picture: thumbs up or down, or 1-5 stars when
// the sheet asks for them. Picking the one that's set takes it back.
import { computed, ref } from 'vue'
import { HandThumbDownIcon, HandThumbUpIcon } from '@heroicons/vue/24/outline'
import { HandThumbDownIcon as HandThumbDownSolid, HandThumbUpIcon as HandThumbUpSolid, StarIcon } from '@heroicons/vue/24/solid'
import type { RatingStyle } from './sheetReview'
import type { SheetContext } from './useContactSheet'

const props = defineProps<{ sheet: SheetContext; anchor: string; rating: RatingStyle; large?: boolean }>()

const THUMBS = [
  { value: 'up' as const, title: 'Thumbs up', outline: HandThumbUpIcon, solid: HandThumbUpSolid, on: 'text-accent-hi' },
  { value: 'down' as const, title: 'Thumbs down', outline: HandThumbDownIcon, solid: HandThumbDownSolid, on: 'text-red-400' },
]
const hover = ref(0)
const review = computed(() => props.sheet.reviewOf(props.anchor))
</script>
