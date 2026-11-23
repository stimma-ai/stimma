<template>
  <!-- A tile's markers, set in place: the ones it has always show, and the
       rest join them on hover. The owner loads markers for its tiles in one batch. -->
  <div
    v-if="availableMarkers.length"
    class="absolute bottom-1.5 left-1.5 right-1.5 z-10 flex flex-wrap gap-0.5"
    data-testid="tile-marker-toggles"
    @click.stop
    @dblclick.stop
  >
    <button
      v-for="marker in availableMarkers"
      :key="marker.id"
      type="button"
      class="h-6 w-6 items-center justify-center rounded-md bg-black/60 backdrop-blur-md transition-colors hover:bg-black/80"
      :class="hasMarker(mediaId, marker.id) ? 'flex' : 'hidden text-white/60 hover:text-white group-hover:flex group-focus-within:flex'"
      :style="hasMarker(mediaId, marker.id) ? { color: marker.color } : undefined"
      :title="hasMarker(mediaId, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
      :aria-pressed="hasMarker(mediaId, marker.id)"
      @click="toggleMarker(mediaId, marker)"
    >
      <span class="icon-container flex h-3.5 w-3.5 items-center justify-center" :class="hasMarker(mediaId, marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { useMarkers } from '../../composables/useMarkers'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

defineProps<{ mediaId: number }>()
const { availableMarkers, hasMarker, toggleMarker } = useMarkers()
</script>
