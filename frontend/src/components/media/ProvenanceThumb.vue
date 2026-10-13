<template>
  <!-- The app host's thumbnail for provenance views: library media through
       MediaImage (context menu, drag), everything else through AppImage. -->
  <MediaImage
    v-if="drawn?.kind === 'media'"
    :media-id="drawn.mediaId"
    :file-path="drawn.filePath || undefined"
    :alt="alt"
    :thumbnail-size="size > 64 ? 256 : 128"
    :contain="true"
    container-class="w-full h-full"
  />
  <AppImage
    v-else-if="url"
    :src="url"
    :alt="alt"
    :contain="true"
    background-class="bg-matte"
    container-class="w-full h-full"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppImage from './AppImage.vue'
import MediaImage from './MediaImage.vue'
import { preprocessedUrl, referenceFileUrl } from './provenancePreviews'
import type { AppThumbRef } from '../../provenance/fromProvenance'

const props = defineProps<{
  thumbRef: AppThumbRef | null
  fallbackRef: AppThumbRef | null
  alt: string
  size: number
}>()

function urlFor(ref: AppThumbRef | null): string {
  if (!ref) return ''
  if (ref.kind === 'file') return referenceFileUrl(ref.filePath)
  if (ref.kind === 'preprocessed') return preprocessedUrl(ref)
  return ''
}

// A preview that hasn't resolved (or can't) draws the source instead.
const drawn = computed<AppThumbRef | null>(() => {
  const ref = props.thumbRef
  if (ref?.kind === 'preprocessed' && !preprocessedUrl(ref)) return props.fallbackRef
  return ref
})
const url = computed(() => urlFor(drawn.value))
</script>
