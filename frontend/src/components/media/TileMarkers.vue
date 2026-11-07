<template>
  <!--
    Display-only state markers: small glyphs on the same black glass as TileChip
    (one 20px square each), so they hold contrast on any image. Each glyph is
    drawn in its marker's own colour; white only when a marker has none.
  -->
  <span v-if="markers.length" :title="names" class="inline-flex max-w-full shrink-0 items-center gap-1.5">
    <span
      v-for="marker in markers"
      :key="marker.id"
      class="flex h-5 w-5 items-center justify-center rounded-md bg-black/55 backdrop-blur-md [&>svg]:h-3.5 [&>svg]:w-3.5"
      :class="colorOf(marker) ? '' : 'text-white/90'"
      :style="colorOf(marker) ? { color: colorOf(marker) } : undefined"
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
function colorOf(marker: TileMarker) {
  return definition(marker)?.color || marker.color
}
function iconSvg(marker: TileMarker) {
  return sanitizeSvg(definition(marker)?.icon_svg || marker.icon_svg || '')
}

const names = computed(() => props.markers.map((m) => definition(m)?.name || m.name).filter(Boolean).join(', '))
</script>
