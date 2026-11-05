<template>
  <TileChip v-if="markers.length" :title="names" class="gap-1.5">
    <span
      v-for="marker in markers"
      :key="marker.id"
      class="flex h-3 w-3 items-center justify-center [&>svg]:h-full [&>svg]:w-full"
      :class="isFavorite(marker) ? '' : 'text-white/90'"
      :style="isFavorite(marker) ? { color: colorOf(marker) } : undefined"
      v-html="iconSvg(marker)"
    />
  </TileChip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import TileChip from './TileChip.vue'
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
