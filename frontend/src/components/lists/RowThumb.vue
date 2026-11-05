<script setup lang="ts">
// The leading thumbnail of a list row. One empty treatment for every row:
// when there is no media, or it fails to load, the row shows a matte tile with
// the row type's glyph (slot) instead of a blank square. The glyph is drawn
// under the image, so a slow, missing, transparent or blank thumbnail never
// reads as an empty slot.
import { ref, watch } from 'vue'
import { MediaImage } from '../media'

const props = defineProps<{
  mediaId?: number | null
  fileHash?: string
  thumbnailSize?: number
}>()

const failed = ref(false)
watch(() => [props.mediaId, props.fileHash], () => { failed.value = false })
</script>

<template>
  <div class="relative flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-media bg-matte text-content-tertiary">
    <!-- The glyph always sits under the image on the same matte, so a thumbnail
         that loads but is transparent or blank still shows the row's type. -->
    <span class="flex h-5 w-5 items-center justify-center" aria-hidden="true">
      <slot />
    </span>
    <div v-if="mediaId != null && !failed" class="absolute inset-0">
      <MediaImage
        :media-id="mediaId"
        :file-hash="fileHash"
        :thumbnail="true"
        :thumbnail-size="thumbnailSize || 80"
        :draggable="false"
        :enable-context-menu="false"
        container-class="w-full h-full"
        background-class="bg-transparent"
        img-class="w-full h-full object-cover"
        @error="failed = true"
      />
    </div>
  </div>
</template>
