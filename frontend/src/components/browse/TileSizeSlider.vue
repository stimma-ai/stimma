<script setup lang="ts">
// Thumbnail size: a grid glyph and a slider, nothing else (no label, no second
// glyph). The value is the minimum tile width; the grid fills the width with
// as many tiles of at least that size as fit. Styled like the app's other
// sliders (MegapixelsPicker): thin track, small accent thumb.
import { Squares2X2Icon } from '@heroicons/vue/24/outline'
import { TILE_MIN } from '../../utils/browseGrouping'

withDefaults(defineProps<{ min?: number, max?: number }>(), { min: TILE_MIN.min, max: TILE_MIN.max })
const model = defineModel<number>({ required: true })
</script>

<template>
  <label class="flex h-control items-center gap-2 coarse:min-h-11" title="Thumbnail size">
    <Squares2X2Icon class="h-icon-nav w-icon-nav flex-none text-content-tertiary" aria-hidden="true" />
    <input
      v-model.number="model"
      type="range"
      :min="min"
      :max="max"
      step="1"
      aria-label="Thumbnail size"
      class="h-1 w-28 cursor-pointer appearance-none rounded-full bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-accent"
    >
  </label>
</template>
