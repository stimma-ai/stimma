<template>
  <!-- Display-only markers on a tile: the shared black-glass chip, each glyph
       in its marker's color (see TileMarkers). -->
  <TileMarkers :markers="markers" :class="small ? '!h-4 !px-1 !gap-1' : ''" />
</template>

<script setup>
import TileMarkers from './media/TileMarkers.vue'

defineProps({
  markers: {
    type: Array,
    default: () => []
  },
  // Compact chip for small tiles (e.g. the media picker popover grid)
  small: {
    type: Boolean,
    default: false
  }
})
</script>
