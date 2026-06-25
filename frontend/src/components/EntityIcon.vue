<template>
  <!--
    EntityIcon — the one shared fallback icon for chats, boards, projects and
    flows. Neutral tile only: a quiet `bg-overlay-faint` tile with a subtle
    border and a `text-content-secondary` glyph. NO gradients — the old
    per-type gradient tiles (green chat / amber board / slate project / violet
    flow) are retired. Route every entity fallback through this component so the
    gradient treatment can't creep back in ad hoc.
  -->
  <div
    class="flex items-center justify-center flex-shrink-0 bg-overlay-faint border border-edge-subtle text-content-secondary"
    :class="[boxClass, shapeClass]"
  >
    <!-- chat -->
    <svg v-if="type === 'chat'" :class="glyphClass" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
    </svg>
    <!-- board -->
    <svg v-else-if="type === 'board'" :class="glyphClass" viewBox="0 0 20 20" fill="currentColor">
      <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5C8.216 18 9 17.216 9 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
    </svg>
    <!-- project -->
    <svg v-else-if="type === 'project'" :class="glyphClass" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
    </svg>
    <!-- flow -->
    <svg v-else :class="glyphClass" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    type: 'chat' | 'board' | 'project' | 'flow'
    /** Tile size. sm = sidebar rows, md/lg = cards & landing screens. */
    size?: 'sm' | 'md' | 'lg'
    /** Tile shape. Defaults to a circle for chats and a rounded square for
     *  everything else; override (e.g. 'rounded') to match a surrounding
     *  square-thumbnail layout. */
    shape?: 'circle' | 'rounded'
  }>(),
  { size: 'sm' }
)

const boxClass = computed(() => {
  switch (props.size) {
    case 'lg':
      return 'w-11 h-11'
    case 'md':
      return 'w-10 h-10'
    case 'sm':
    default:
      return 'w-8 h-8'
  }
})

// Square types: rounded-lg for sidebar rows & standard cards, a touch rounder
// (rounded-xl) for the largest landing-card tiles.
const radiusClass = computed(() => (props.size === 'lg' ? 'rounded-xl' : 'rounded-lg'))

const shapeClass = computed(() => {
  const shape = props.shape ?? (props.type === 'chat' ? 'circle' : 'rounded')
  return shape === 'circle' ? 'rounded-full' : radiusClass.value
})

const glyphClass = computed(() => (props.size === 'sm' ? 'w-4 h-4' : 'w-5 h-5'))
</script>
