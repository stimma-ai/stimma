<template>
  <div class="flex" :class="small ? 'gap-0.5' : 'gap-1'">
    <div
      v-for="marker in markers"
      :key="marker.id"
      class="bg-black/60 backdrop-blur-md rounded flex items-center justify-center"
      :class="small ? 'w-4 h-4' : 'w-6 h-6'"
      :title="getMarkerDef(marker.id)?.name || marker.name"
    >
      <span
        class="flex items-center justify-center icon-container"
        :class="small ? 'w-3 h-3' : 'w-4 h-4'"
        :style="{ color: getMarkerDef(marker.id)?.color || marker.color }"
        v-html="markerIconSvg(marker)"
      />
    </div>
  </div>
</template>

<script setup>
import { useMarkers } from '../composables/useMarkers'
import { sanitizeSvg } from '../utils/sanitizeHtml'

defineProps({
  markers: {
    type: Array,
    default: () => []
  },
  // Compact badges for small tiles (e.g. the media picker popover grid)
  small: {
    type: Boolean,
    default: false
  }
})

const { availableMarkers } = useMarkers()

// Look up current marker definition by ID to get live icon/color
function getMarkerDef(id) {
  return availableMarkers.value.find(m => m.id === id)
}

function markerIconSvg(marker) {
  return sanitizeSvg(getMarkerDef(marker.id)?.icon_svg || marker.icon_svg)
}
</script>

<style scoped>
/* SVG sizing */
:deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
