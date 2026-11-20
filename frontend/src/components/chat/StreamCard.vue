<template>
  <!-- An open-ended run ("until I say stop") while it runs: the newest results
       come in from the left and the card only says it is still going. No
       count: there is no total to count toward. When the run ends the chat
       shows the whole collection instead. -->
  <div class="bg-surface rounded-lg p-3 w-full max-w-[640px]">
    <div class="flex items-baseline justify-between gap-4 mb-2.5">
      <span class="text-sm text-content-secondary font-medium truncate">{{ title }}</span>
      <span class="flex flex-none items-center gap-1.5 text-xs text-content-tertiary">
        <span class="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse-soft"></span>
        Generating…
      </span>
    </div>
    <div class="relative overflow-hidden">
      <div class="flex gap-1.5">
        <span class="h-[72px] w-[72px] flex-shrink-0 rounded-media bg-surface-active animate-pulse-soft" aria-hidden="true"></span>
        <button
          v-for="tile in recent"
          :key="tile.key"
          type="button"
          class="relative h-[72px] w-[72px] flex-shrink-0 rounded-media overflow-hidden bg-matte hover:ring-2 hover:ring-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          :aria-label="`Result ${tile.index + 1}`"
          @click="$emit('view-image', tile.mediaId, tile.index)"
        >
          <MediaImage
            :media-id="tile.mediaId"
            :thumbnail="true"
            container-class="w-full h-full"
            img-class="w-full h-full object-cover"
            loading="lazy"
          />
        </button>
      </div>
      <div class="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-surface to-transparent"></div>
    </div>
    <button
      v-if="recent.length"
      type="button"
      class="mt-2 text-xs text-content-tertiary hover:text-content-secondary transition-colors"
      @click="$emit('see-all')"
    >See all</button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { MediaImage } from '../media'

const props = defineProps({
  title: { type: String, default: '' },
  rows: { type: Array, default: () => [] },
})
defineEmits(['view-image', 'see-all'])

// Newest first. Rows arrive in the order their calls started, so the latest
// finished ones are at the end.
const RECENT = 12
const recent = computed(() => props.rows
  .map((row, index) => ({ row, index }))
  .filter(({ row }) => row.output?.status === 'complete' && row.output.media_id)
  .slice(-RECENT)
  .reverse()
  .map(({ row, index }) => ({ key: row.id, index, mediaId: row.output.media_id })))
</script>
