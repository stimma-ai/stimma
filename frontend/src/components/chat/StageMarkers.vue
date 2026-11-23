<template>
  <!-- The artwork's markers, in the artifact panel's header. Same buttons as the
       chat media strip's marker row. A narrow panel keeps the first three
       inline and folds the rest behind +N, like the slideshow's marker controls. -->
  <div v-if="availableMarkers.length" ref="rootRef" class="relative flex items-center" aria-label="Markers" data-testid="stage-markers">
    <button
      v-for="marker in inlineMarkers"
      :key="marker.id"
      type="button"
      class="flex h-7 w-7 flex-none items-center justify-center rounded-md transition-colors hover:bg-overlay-subtle"
      :class="hasMarker(mediaId, marker.id) ? '' : 'text-content-tertiary hover:text-content'"
      :style="hasMarker(mediaId, marker.id) ? { color: marker.color } : undefined"
      :title="hasMarker(mediaId, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
      :aria-pressed="hasMarker(mediaId, marker.id)"
      @click.stop="toggleMarker(mediaId, marker)"
    >
      <span class="icon-container flex h-4 w-4 items-center justify-center" :class="hasMarker(mediaId, marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
    </button>
    <button
      v-if="folded"
      type="button"
      class="flex h-7 min-w-7 flex-none items-center justify-center rounded-md px-1 font-mono text-[11px] transition-colors hover:bg-overlay-subtle"
      :class="hiddenActive ? 'text-content' : 'text-content-secondary'"
      :aria-label="`${availableMarkers.length - FOLD_TO} more markers`"
      :aria-expanded="open"
      @click.stop="open = !open"
    >+{{ availableMarkers.length - FOLD_TO }}</button>
    <div
      v-if="open"
      data-escape-layer
      class="absolute left-0 top-full z-menu mt-1 flex max-w-[16rem] flex-wrap gap-0.5 rounded-lg border border-edge-subtle bg-surface p-1 shadow-lg"
      @click.stop
    >
      <button
        v-for="marker in availableMarkers"
        :key="marker.id"
        type="button"
        class="flex h-8 w-8 flex-none items-center justify-center rounded-md transition-colors hover:bg-overlay-subtle"
        :class="hasMarker(mediaId, marker.id) ? '' : 'text-content-tertiary hover:text-content'"
        :style="hasMarker(mediaId, marker.id) ? { color: marker.color } : undefined"
        :title="hasMarker(mediaId, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
        :aria-pressed="hasMarker(mediaId, marker.id)"
        @click="toggleMarker(mediaId, marker)"
      >
        <span class="icon-container flex h-4 w-4 items-center justify-center" :class="hasMarker(mediaId, marker.id) ? '' : 'marker-glyph-off'" v-html="sanitizeSvg(marker.icon_svg)" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useMarkers } from '../../composables/useMarkers'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { consumeEscape } from '../../utils/escapeLayers'

const props = defineProps<{ mediaId: number; narrow?: boolean }>()

const FOLD_TO = 3
const { availableMarkers, hasMarker, toggleMarker, loadMarkersForMedia } = useMarkers()
watch(() => props.mediaId, id => { if (id != null) loadMarkersForMedia([id]) }, { immediate: true })

const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)
// Four fit without folding; past that a narrow panel shows three and +N.
const folded = computed(() => !!props.narrow && availableMarkers.value.length > FOLD_TO + 1)
const inlineMarkers = computed(() => (folded.value ? availableMarkers.value.slice(0, FOLD_TO) : availableMarkers.value))
const hiddenActive = computed(() => folded.value && availableMarkers.value.slice(FOLD_TO).some((m: any) => hasMarker(props.mediaId, m.id)))
watch(folded, f => { if (!f) open.value = false })

function onDocumentClick(e: MouseEvent) {
  if (open.value && rootRef.value && !rootRef.value.contains(e.target as Node)) open.value = false
}
function onDocumentKeydown(e: KeyboardEvent) {
  if (open.value && e.key === 'Escape') { consumeEscape(e); open.value = false }
}
document.addEventListener('click', onDocumentClick)
document.addEventListener('keydown', onDocumentKeydown, true)
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown, true)
})
</script>
