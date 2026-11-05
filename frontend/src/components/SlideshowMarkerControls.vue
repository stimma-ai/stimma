<script setup>
import { computed, onDeactivated, ref } from 'vue'
import Sheet from './ui/Sheet.vue'
import { sanitizeSvg } from '../utils/sanitizeHtml'

const props = defineProps({
  markers: { type: Array, default: () => [] },
  isActive: { type: Function, required: true },
})
defineEmits(['toggle'])
const open = ref(false)
onDeactivated(() => { open.value = false })
// Four fit at 320px without shrinking the touch targets. Reserve the fourth
// slot for overflow only when the catalog actually needs it; preserve order.
const inlineMarkers = computed(() => props.markers.length > 4 ? props.markers.slice(0, 3) : props.markers)
</script>

<template>
  <div class="flex items-center justify-center gap-0.5" aria-label="Image markers">
    <button v-for="marker in inlineMarkers" :key="marker.id" type="button"
      class="flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      :class="isActive(marker.id) ? 'bg-overlay-light' : 'text-content-tertiary hover:bg-overlay-subtle hover:text-content'"
      :aria-label="marker.name" :aria-pressed="isActive(marker.id)"
      :style="isActive(marker.id) ? { color: marker.color } : undefined"
      @click.stop="$emit('toggle', marker.id)">
      <span class="icon-container flex h-6 w-6 items-center justify-center" :class="isActive(marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
    </button>
    <button v-if="markers.length > 4" type="button"
      class="flex h-11 w-11 shrink-0 items-center justify-center rounded-md font-mono text-xs text-content-secondary hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      :aria-label="`${markers.length - 3} more markers`" @click="open = true">+{{ markers.length - 3 }}</button>
    <Sheet :show="open" @close="open = false">
      <div class="px-4 pb-2">
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium text-content">Markers</span>
          <button type="button" class="min-h-11 min-w-11 text-sm text-content-secondary" @click="open = false">Done</button>
        </div>
        <!-- The icon is a marker's identity; names stay in settings. -->
        <div class="my-2 flex flex-wrap gap-0.5">
          <button v-for="marker in markers" :key="marker.id" type="button"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            :class="isActive(marker.id) ? 'bg-overlay-light' : 'text-content-tertiary hover:bg-overlay-subtle hover:text-content'"
            :aria-label="marker.name" :aria-pressed="isActive(marker.id)"
            :style="isActive(marker.id) ? { color: marker.color } : undefined"
            @click="$emit('toggle', marker.id)">
            <span class="icon-container flex h-6 w-6 items-center justify-center" :class="isActive(marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
          </button>
        </div>
      </div>
    </Sheet>
  </div>
</template>
