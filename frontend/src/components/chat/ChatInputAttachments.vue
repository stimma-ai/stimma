<template>
  <div v-if="attachments.length > 0" class="chat-attachments flex gap-2 overflow-x-auto p-2 bg-surface/50 border-b border-edge">
    <div
      v-for="(attachment, index) in attachments"
      :key="attachment.id || index"
      class="relative overflow-hidden group flex-shrink-0"
      :class="attachment.workspace_ref ? 'flex items-center gap-2 min-h-11 max-w-64 pl-2 pr-10 rounded-md bg-surface-raised' : 'w-16 h-16 bg-matte rounded-media'"
    >
      <!-- Library media (has media_id) - draggable with context menu -->
      <template v-if="attachment.workspace_ref">
        <FileTypeBadge :name="attachment.filename || attachment.workspace_ref.path" />
        <span class="text-xs truncate text-content">{{ attachment.filename }}</span>
      </template>
      <MediaImage
        v-else-if="attachment.media_id"
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
      <IconButton title="Remove attachment" class="absolute top-0 right-0" @click="removeAttachment(index)">
        <XMarkIcon class="w-3.5 h-3.5" />
      </IconButton>
    </div>
  </div>
</template>

<script setup>
import FileTypeBadge from './FileTypeBadge.vue'
import IconButton from '../ui/IconButton.vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'
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
