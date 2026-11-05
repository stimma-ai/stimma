<script setup lang="ts">
// The leading thumbnail of a list row. One empty treatment for every row:
// when there is no media, or it fails to load, the row shows a matte tile with
// the row type's glyph (slot) instead of a blank square. The glyph also holds
// the tile until the image has actually loaded, so a slow or missing thumbnail
// never reads as an empty loading slot.
import { ref, watch } from 'vue'
import { MediaImage } from '../media'

const props = defineProps<{
  mediaId?: number | null
  fileHash?: string
  thumbnailSize?: number
}>()

const failed = ref(false)
const loaded = ref(false)
watch(() => [props.mediaId, props.fileHash], () => { failed.value = false; loaded.value = false })
</script>

<template>
  <div class="relative flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-media bg-matte text-content-tertiary">
    <div v-if="mediaId != null && !failed" class="absolute inset-0">
    <MediaImage
      :media-id="mediaId"
      :file-hash="fileHash"
      :thumbnail="true"
      :thumbnail-size="thumbnailSize || 80"
      :draggable="false"
      :enable-context-menu="false"
      container-class="w-full h-full"
      img-class="w-full h-full object-cover"
      @load="loaded = true"
      @error="failed = true"
    />
    </div>
    <span v-if="mediaId == null || failed || !loaded" class="flex h-5 w-5 items-center justify-center" aria-hidden="true">
      <slot />
    </span>
  </div>
</template>
