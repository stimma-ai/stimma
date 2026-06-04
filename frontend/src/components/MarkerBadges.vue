<template>
  <div class="flex gap-1">
    <div
      v-for="marker in markers"
      :key="marker.id"
      class="w-6 h-6 bg-black/60 backdrop-blur-md rounded flex items-center justify-center"
      :title="getMarkerDef(marker.id)?.name || marker.name"
    >
      <span
        class="w-4 h-4 flex items-center justify-center icon-container"
        :style="{ color: getMarkerDef(marker.id)?.color || marker.color }"
        v-html="getMarkerDef(marker.id)?.icon_svg || marker.icon_svg"
      />
    </div>
  </div>
</template>

<script setup>
import { useMarkers } from '../composables/useMarkers'

defineProps({
  markers: {
    type: Array,
    default: () => []
  }
})

const { availableMarkers } = useMarkers()

// Look up current marker definition by ID to get live icon/color
function getMarkerDef(id) {
  return availableMarkers.value.find(m => m.id === id)
}
</script>

<style scoped>
/* SVG sizing */
:deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
