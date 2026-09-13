<template>
  <!-- A package viewer is the cover and nothing else. Everything you can know
       or do about the bundle (what it holds, whether it is stale, rebuild,
       export) belongs to the media info panel, so the viewer never grows a
       second sidebar beside it. -->
  <div class="relative h-full w-full overflow-hidden bg-matte">
    <!-- A real URL, not srcdoc: relative links to sibling files inside the
         bundle (previews, run zips, extras) only resolve when the frame has
         the package-file route as its base. -->
    <iframe
      v-if="coverUrl"
      :src="coverUrl"
      sandbox="allow-scripts allow-same-origin allow-downloads allow-popups"
      class="h-full w-full border-0 bg-matte"
      title="Package cover"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { getApiBase } from '../../apiConfig'
import { getCurrentDbGuid, getCurrentProfileId } from '../../composables/useProfile'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true,
  },
})

// A rebuild commits a new revision, which hands this viewer a new media id
// through the prop — nothing to track locally.
const coverUrl = computed(() => {
  if (!props.mediaId) return ''
  const dbGuid = getCurrentDbGuid()
  if (dbGuid) {
    return `${getApiBase()}/db/${dbGuid}/media/${props.mediaId}/package-file/index.html`
  }
  return `${getApiBase()}/media/${props.mediaId}/package-file/index.html?profile=${encodeURIComponent(getCurrentProfileId())}`
})
</script>
