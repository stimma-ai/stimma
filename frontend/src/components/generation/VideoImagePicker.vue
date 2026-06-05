<template>
  <div class="space-y-3 mb-6">
    <label class="text-xs font-medium text-content-muted uppercase tracking-wide">Reference Frames</label>

    <div class="flex gap-3">
      <!-- Start Frame (Required) -->
      <div>
        <div class="text-xs text-content-muted mb-2">Start Frame</div>
        <div
          v-if="startImage"
          class="relative w-48 h-48 border border-surface-raised rounded-lg overflow-hidden group"
          @dragenter.prevent.stop="onDragOverStart"
          @dragover.prevent.stop="onDragOverStart"
          @dragleave.prevent.stop="onDragLeaveStart"
          @drop.prevent.stop="onDropStart"
        >
          <AppImage
            :src="getImageUrl(startImage)"
            alt="Start frame"
            contain
            container-class="w-full h-full"
            :img-class="startImage.mediaId ? 'cursor-pointer' : ''"
            @click="onImageClick(startImage)"
          />
          <button
            @click="removeStartImage"
            class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-white">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>
        <div
          v-else
          @click="openFilePickerStart"
          @dragenter.prevent.stop="onDragOverStart"
          @dragover.prevent.stop="onDragOverStart"
          @dragleave.prevent.stop="onDragLeaveStart"
          @drop.prevent.stop="onDropStart"
          :class="[
            'w-48 h-48 bg-surface border-2 border-dashed rounded-lg flex flex-col items-center justify-center gap-1 transition-colors cursor-pointer',
            isDraggingStart ? 'border-blue-500 bg-blue-500/10' : 'border-edge hover:border-blue-500 hover:bg-surface'
          ]"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6 text-content-muted">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          <span class="text-xs text-content-muted">{{ isDraggingStart ? 'Drop here' : 'Add' }}</span>
        </div>
      </div>

      <!-- End Frame (Optional) -->
      <div v-if="showEndFrame !== false">
        <div class="text-xs text-content-muted mb-2">End Frame (optional)</div>
        <div
          v-if="endImage"
          class="relative w-48 h-48 border border-surface-raised rounded-lg overflow-hidden group"
          @dragenter.prevent.stop="onDragOverEnd"
          @dragover.prevent.stop="onDragOverEnd"
          @dragleave.prevent.stop="onDragLeaveEnd"
          @drop.prevent.stop="onDropEnd"
        >
          <AppImage
            :src="getImageUrl(endImage)"
            alt="End frame"
            contain
            container-class="w-full h-full"
            :img-class="endImage.mediaId ? 'cursor-pointer' : ''"
            @click="onImageClick(endImage)"
          />
          <button
            @click="removeEndImage"
            class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-white">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>
        <div
          v-else
          @click="openFilePickerEnd"
          @dragenter.prevent.stop="onDragOverEnd"
          @dragover.prevent.stop="onDragOverEnd"
          @dragleave.prevent.stop="onDragLeaveEnd"
          @drop.prevent.stop="onDropEnd"
          :class="[
            'w-48 h-48 bg-surface border-2 border-dashed rounded-lg flex flex-col items-center justify-center gap-1 transition-colors cursor-pointer',
            isDraggingEnd ? 'border-blue-500 bg-blue-500/10' : 'border-edge hover:border-blue-500 hover:bg-surface'
          ]"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6 text-content-muted">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          <span class="text-xs text-content-muted">{{ isDraggingEnd ? 'Drop here' : 'Add' }}</span>
        </div>
      </div>
    </div>

    <!-- Loading indicator -->
    <div v-if="isUploading" class="flex items-center gap-2 text-sm text-content-muted">
      <div class="w-4 h-4 border-2 border-edge border-t-blue-500 rounded-full animate-spin"></div>
      <span>Uploading...</span>
    </div>

    <!-- Hidden file inputs -->
    <input v-no-autocorrect
      ref="fileInputStart"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="handleFileSelectStart"
    >
    <input v-no-autocorrect
      ref="fileInputEnd"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="handleFileSelectEnd"
    >
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import axios from 'axios'
import { useMediaApi } from '../../composables/useMediaApi'
import AppImage from '../media/AppImage.vue'

import { getApiBase } from '../../apiConfig'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
const { getMediaFileUrl, getMediaItem } = useMediaApi()

interface VideoImage {
  path: string
  filename: string
  hash?: string
  mediaId?: number
}

interface Props {
  startImage: VideoImage | null
  endImage: VideoImage | null
  showEndFrame?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:startImage', value: VideoImage | null): void
  (e: 'update:endImage', value: VideoImage | null): void
  (e: 'view-image', mediaId: number): void
}>()

const API_BASE = '/api'

const fileInputStart = ref<HTMLInputElement | null>(null)
const fileInputEnd = ref<HTMLInputElement | null>(null)
const isUploading = ref(false)
const isDraggingStart = ref(false)
const isDraggingEnd = ref(false)

function getImageUrl(image: VideoImage): string {
  // Use original file instead of thumbnail for better quality display
  if (image.hash) {
    return getMediaFileUrl(image.hash)
  }
  if (!image.path) {
    if (image.filename) {
      return getMediaFileUrl(image.filename)
    }
    return ''
  }
  if (image.path.startsWith('/')) {
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(image.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  // Otherwise assume path is a hash - use original file
  return getMediaFileUrl(image.path)
}

function onImageClick(image: VideoImage) {
  // Only emit if the image has a mediaId (from media library)
  if (image.mediaId) {
    emit('view-image', image.mediaId)
  }
}

// Start frame handlers
function openFilePickerStart() {
  fileInputStart.value?.click()
}

function onDragOverStart() {
  isDraggingStart.value = true
}

function onDragLeaveStart() {
  isDraggingStart.value = false
}

async function onDropStart(event: DragEvent) {
  isDraggingStart.value = false

  // Check for media ID from media library drag
  const mediaId = event.dataTransfer?.getData('application/x-media-id')
  if (mediaId) {
    await addFromMediaId(parseInt(mediaId), 'start')
    return
  }

  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return
  const file = Array.from(files).find(f => f.type.startsWith('image/'))
  if (!file) return
  await uploadFile(file, 'start')
}

async function handleFileSelectStart(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  input.value = ''
  await uploadFile(file, 'start')
}

async function removeStartImage() {
  // Don't delete from server - keep uploads persistent for history
  emit('update:startImage', null)
}

// End frame handlers
function openFilePickerEnd() {
  fileInputEnd.value?.click()
}

function onDragOverEnd() {
  isDraggingEnd.value = true
}

function onDragLeaveEnd() {
  isDraggingEnd.value = false
}

async function onDropEnd(event: DragEvent) {
  isDraggingEnd.value = false

  // Check for media ID from media library drag
  const mediaId = event.dataTransfer?.getData('application/x-media-id')
  if (mediaId) {
    await addFromMediaId(parseInt(mediaId), 'end')
    return
  }

  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return
  const file = Array.from(files).find(f => f.type.startsWith('image/'))
  if (!file) return
  await uploadFile(file, 'end')
}

async function handleFileSelectEnd(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  input.value = ''
  await uploadFile(file, 'end')
}

async function removeEndImage() {
  // Don't delete from server - keep uploads persistent for history
  emit('update:endImage', null)
}

// Add from media library drag
async function addFromMediaId(mediaId: number, target: 'start' | 'end') {
  isUploading.value = true
  try {
    const mediaItem = await getMediaItem(mediaId)

    // Copy the media to reference directory
    let path = mediaItem.file_path
    let filename = mediaItem.file_path?.split('/').pop() || `media.${mediaItem.file_format}`

    try {
      const response = await axios.post(
        `${API_BASE}/generate/copy-to-reference?source_path=${encodeURIComponent(mediaItem.file_path)}`
      )
      path = response.data.path
      filename = response.data.filename
    } catch (err) {
      console.error('Error copying media to reference:', err)
    }

    const newImage: VideoImage = {
      path,
      filename,
      hash: mediaItem.file_hash,
      mediaId: mediaItem.id,
    }

    if (target === 'start') {
      emit('update:startImage', newImage)
    } else {
      emit('update:endImage', newImage)
    }
  } catch (error) {
    console.error('Failed to add from media library:', error)
  } finally {
    isUploading.value = false
  }
}

// Shared upload function
async function uploadFile(file: File, target: 'start' | 'end') {
  isUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await axios.post(`${API_BASE}/generate/upload-reference`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    const newImage: VideoImage = {
      path: response.data.path,
      filename: response.data.filename,
      hash: response.data.file_hash,
      mediaId: response.data.media_id,
    }

    if (target === 'start') {
      emit('update:startImage', newImage)
    } else {
      emit('update:endImage', newImage)
    }
  } catch (error) {
    console.error('Failed to upload video frame:', error)
  } finally {
    isUploading.value = false
  }
}
</script>
