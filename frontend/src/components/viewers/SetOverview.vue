<template>
  <div
    ref="containerRef"
    class="w-full h-full bg-slideshow-matt flex flex-col overflow-hidden"
  >
    <!-- Main content area with explicit scroll -->
    <div
      ref="scrollContainerRef"
      class="flex-1 overflow-auto p-6 pt-20 min-h-0 custom-scrollbar"
    >
      <div v-if="loading" class="flex items-center justify-center h-full text-content-tertiary">
        Loading set...
      </div>

      <div v-else-if="error" class="flex items-center justify-center h-full text-red-500">
        {{ error }}
      </div>

      <div v-else-if="items.length === 0" class="flex items-center justify-center h-full text-content-tertiary">
        This set is empty
      </div>

      <div v-else class="flex flex-wrap gap-3 justify-center">
        <div
          v-for="(item, index) in items"
          :key="mediaIdOf(item.resolved) || index"
          class="group w-48 h-48 bg-base rounded overflow-hidden cursor-pointer transition-all relative hover:ring-2 hover:ring-cyan-400"
          :draggable="!!item.resolved"
          @click="selectItem(index, item)"
          @dragstart="handleItemDragStart($event, item.resolved)"
          @dragend="handleItemDragEnd"
        >
          <MediaImage
            v-if="item.resolved"
            :media-id="mediaIdOf(item.resolved)"
            :file-hash="item.resolved.file_hash"
            :file-path="item.resolved.file_path"
            :file-format="item.resolved.file_format"
            :alt="item.resolved.vlm_caption || 'Set item'"
            thumbnail
            :thumbnail-size="256"
            :draggable="false"
            container-class="w-full h-full"
            img-class="w-full h-full object-cover"
          />
          <div v-else class="w-full h-full flex items-center justify-center text-content-muted">
            <svg class="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'
import { MediaImage } from '../media'
import axios from 'axios'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['select-item', 'loaded'])

const { getThumbnailUrl } = useMediaApi()

const containerRef = ref(null)
const scrollContainerRef = ref(null)
const loading = ref(true)
const error = ref(null)
const title = ref('')
const description = ref('')
const items = ref([])

async function loadContent() {
  loading.value = true
  error.value = null

  try {
    const response = await axios.get(`/api/media/${props.mediaId}/content`)
    const data = response.data

    title.value = data.title || ''
    description.value = data.description || ''
    items.value = data.items || []

    emit('loaded', { title: title.value, description: description.value })
  } catch (e) {
    console.error('Failed to load set content:', e)
    error.value = 'Failed to load set content'
  } finally {
    loading.value = false
  }
}

function selectItem(index, item) {
  if (!item.resolved) return

  emit('select-item', {
    index,
    item,
    setData: {
      title: title.value,
      description: description.value,
      items: items.value
    }
  })
}

function mediaIdOf(media) {
  return media?.id ?? media?.media_id ?? undefined
}

function isVideoFormat(fileFormat) {
  return ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes((fileFormat || '').toLowerCase())
}

function handleItemDragStart(event, media) {
  const mediaId = mediaIdOf(media)
  if (!mediaId || !media?.file_hash) return

  const thumbnailUrl = getThumbnailUrl(media.file_hash, 128)
  createDragPreview(event, thumbnailUrl, mediaId, media.file_format || '', isVideoFormat(media.file_format))
}

function handleItemDragEnd() {
  handleDragEnd()
}

onMounted(() => {
  loadContent()
})

watch(() => props.mediaId, () => {
  loadContent()
})
</script>
