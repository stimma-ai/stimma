<template>
  <!--
    Display-only state markers: bare glyphs with a soft shadow, no plate, so a
    marker reads as a property of the picture and never as a button. White in
    both themes; the one colour is an active favorite heart.
  -->
  <span v-if="markers.length" :title="names" class="inline-flex max-w-full shrink-0 items-center gap-1.5">
    <span
      v-for="marker in markers"
      :key="marker.id"
      class="flex h-4 w-4 items-center justify-center [filter:drop-shadow(0_0_1px_rgb(0_0_0/0.6))_drop-shadow(0_1px_2px_rgb(0_0_0/0.65))] [&>svg]:h-full [&>svg]:w-full"
      :class="isFavorite(marker) ? '' : 'text-white/90'"
      :style="isFavorite(marker) ? { color: colorOf(marker) } : undefined"
      v-html="iconSvg(marker)"
    />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useMarkers } from '../../composables/useMarkers'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

type TileMarker = { id: number | string; name?: string; color?: string; icon_svg?: string }

const props = defineProps<{ markers: TileMarker[] }>()

const { availableMarkers } = useMarkers()

function definition(marker: TileMarker): TileMarker | undefined {
  return availableMarkers.value.find((m: TileMarker) => m.id === marker.id)
}
function isFavorite(marker: TileMarker) {
  return (definition(marker)?.name ?? marker.name) === 'favorite'
}
function colorOf(marker: TileMarker) {
  return definition(marker)?.color || marker.color
}
function iconSvg(marker: TileMarker) {
  return sanitizeSvg(definition(marker)?.icon_svg || marker.icon_svg || '')
}

const names = computed(() => props.markers.map((m) => definition(m)?.name || m.name).filter(Boolean).join(', '))
</script>
