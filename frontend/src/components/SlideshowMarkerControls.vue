<script setup>
import { computed, onDeactivated, ref } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/outline'
import Sheet from './ui/Sheet.vue'
import { sanitizeSvg } from '../utils/sanitizeHtml'

const props = defineProps({
  markers: { type: Array, default: () => [] },
  isActive: { type: Function, required: true },
})
defineEmits(['toggle'])
const open = ref(false)
const search = ref('')
onDeactivated(() => { open.value = false })
// Four fit at 320px without shrinking the touch targets. Reserve the fourth
// slot for overflow only when the catalog actually needs it; preserve order.
const inlineMarkers = computed(() => props.markers.length > 4 ? props.markers.slice(0, 3) : props.markers)
const filteredMarkers = computed(() => props.markers.filter(marker => marker.name.toLowerCase().includes(search.value.trim().toLowerCase())))
</script>

<template>
  <div class="flex items-center justify-center gap-0.5" aria-label="Image markers">
    <button v-for="marker in inlineMarkers" :key="marker.id" type="button"
      class="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-content-secondary transition-colors hover:bg-overlay-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      :aria-label="marker.name" :aria-pressed="isActive(marker.id)"
      :style="isActive(marker.id) ? { color: marker.color } : undefined"
      @click.stop="$emit('toggle', marker.id)">
      <span class="icon-container flex h-6 w-6 items-center justify-center" v-html="sanitizeSvg(marker.icon_svg)" />
    </button>
    <button v-if="markers.length > 4" type="button"
      class="flex h-11 w-11 shrink-0 items-center justify-center rounded-md font-mono text-xs text-content-secondary hover:bg-overlay-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      :aria-label="`${markers.length - 3} more markers`" @click="search = ''; open = true">+{{ markers.length - 3 }}</button>
    <Sheet :show="open" @close="open = false">
      <div class="px-4 pb-2">
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium text-content">Markers</span>
          <button type="button" class="min-h-11 min-w-11 text-sm text-content-secondary" @click="open = false">Done</button>
        </div>
        <input v-model="search" type="search" aria-label="Find marker" placeholder="Find marker…"
          class="my-2 min-h-11 w-full rounded-md border-0 bg-overlay-faint px-3 text-base text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent" />
        <button v-for="marker in filteredMarkers" :key="marker.id" type="button" class="sheet-row !px-0"
          :aria-label="marker.name" :aria-pressed="isActive(marker.id)" @click="$emit('toggle', marker.id)">
          <span class="sheet-row-icon icon-container" :style="isActive(marker.id) ? { color: marker.color } : undefined" v-html="sanitizeSvg(marker.icon_svg)" />
          <span class="flex-1">{{ marker.name }}</span>
          <CheckIcon v-if="isActive(marker.id)" class="h-5 w-5 text-content-secondary" />
        </button>
        <p v-if="!filteredMarkers.length" class="py-4 text-sm text-content-tertiary">No markers found</p>
      </div>
    </Sheet>
  </div>
</template>
