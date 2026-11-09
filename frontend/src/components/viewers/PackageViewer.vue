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
      ref="frame"
      :src="coverUrl"
      sandbox="allow-scripts allow-same-origin allow-downloads allow-popups"
      class="h-full w-full border-0 bg-matte"
      title="Package cover"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { getApiBase } from '../../apiConfig'
import { getCurrentDbGuid, getCurrentProfileId } from '../../composables/useProfile'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true,
  },
})

// The cover's bridge (in-app responses only) hands out what it did not use:
// Escape, the viewer's ←/→, and a right-click on the page itself.
const emit = defineEmits(['escape', 'key', 'frame-contextmenu'])
const frame = ref(null)
function onFrameMessage(event) {
  if (!frame.value?.contentWindow || event.source !== frame.value.contentWindow) return
  const type = event.data?.type
  if (type === 'stimma-package-escape') {
    emit('escape', new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
  } else if (type === 'stimma-package-key' && ['ArrowLeft', 'ArrowRight'].includes(event.data.key)) {
    emit('key', new KeyboardEvent('keydown', { key: event.data.key, cancelable: true }))
  } else if (type === 'stimma-package-contextmenu') {
    const rect = frame.value.getBoundingClientRect()
    // The menu opens in this page; its keys (Escape) must reach it here.
    frame.value.blur()
    emit('frame-contextmenu', frameContextMenuEvent(rect.left + Number(event.data.x || 0), rect.top + Number(event.data.y || 0)))
  }
}
function frameContextMenuEvent(clientX, clientY) {
  return { clientX, clientY, preventDefault() {}, stopPropagation() {} }
}
onMounted(() => window.addEventListener('message', onFrameMessage))
onBeforeUnmount(() => window.removeEventListener('message', onFrameMessage))

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
