<template>
  <div v-if="attachments.length > 0" class="chat-attachments flex gap-2 p-2 bg-surface/50 border-b border-edge">
    <div
      v-for="(attachment, index) in attachments"
      :key="attachment.id || index"
      class="relative w-16 h-16 bg-surface-raised rounded overflow-hidden group flex-shrink-0"
    >
      <!-- Library media (has media_id) - draggable with context menu -->
      <MediaImage
        v-if="attachment.media_id"
        :media-id="attachment.media_id"
        :thumbnail="true"
        :thumbnail-size="128"
        container-class="w-full h-full"
      />
      <!-- Reference file or blob URL - not draggable -->
      <AppImage
        v-else
        :src="getAttachmentUrl(attachment)"
        :alt="`Attachment ${index + 1}`"
        container-class="w-full h-full"
      />
      <!-- Remove button -->
      <button
        @click="removeAttachment(index)"
        class="absolute top-0.5 right-0.5 w-5 h-5 bg-black/70 hover:bg-red-500 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { MediaImage, AppImage } from '../media'
import { getApiBase } from '../../apiConfig'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'

const props = defineProps({
  attachments: {
    type: Array,
    required: true
  }
})

const emit = defineEmits(['remove'])

function getAttachmentUrl(attachment) {
  // If it's an uploaded file with a path
  if (attachment.path) {
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(attachment.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  // If it has a local blob URL (during upload)
  if (attachment.localUrl) {
    return attachment.localUrl
  }
  return ''
}

function removeAttachment(index) {
  emit('remove', index)
}
</script>
