<template>
  <div class="flex justify-start w-full max-w-3xl">
    <div class="bg-surface rounded-lg p-3">
      <!-- Header with tool name -->
      <div v-if="toolName || description" class="flex items-center gap-2 mb-2">
        <span
          v-if="toolName"
          class="px-2 py-0.5 rounded text-xs font-medium bg-purple-500/20 border border-purple-500/50 text-purple-500"
        >
          {{ formatToolName(toolName) }}
        </span>
        <span v-if="description" class="text-xs text-content-tertiary truncate">
          {{ description }}
        </span>
      </div>

      <!-- Before/After layout when source image exists -->
      <div v-if="sourceMediaId && images.length > 0" class="flex gap-3">
        <!-- Source (Before) -->
        <div>
          <div class="text-xs text-content-muted mb-1">Original</div>
          <MediaImage
            :media-id="sourceMediaId"
            :thumbnail="false"
            :contain="true"
            alt="Original"
            container-class="cursor-pointer rounded max-h-[300px]"
            img-class="max-h-[300px]"
            @click="handleSourceClick"
          />
        </div>
        <!-- Result (After) -->
        <div>
          <div class="text-xs text-content-muted mb-1">Result</div>
          <MediaImage
            :media-id="images[0].media_id"
            :thumbnail="false"
            :contain="true"
            alt="Result"
            container-class="cursor-pointer rounded max-h-[300px]"
            img-class="max-h-[300px]"
            @click="handleImageClick(images[0].media_id, 0)"
          />
        </div>
      </div>

      <!-- Regular grid (no source image) -->
      <div v-else-if="images.length > 0" class="grid gap-2" :class="gridClass">
        <MediaImage
          v-for="(image, index) in images"
          :key="image.media_id"
          :media-id="image.media_id"
          :thumbnail="true"
          :contain="true"
          :alt="image.prompt || image.caption || 'Image'"
          container-class="relative group cursor-pointer rounded max-h-[300px]"
          img-class="max-h-[300px]"
          @click="handleImageClick(image.media_id, index)"
        >
          <!-- Hover overlay with info -->
          <div class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity rounded flex items-end p-1 z-10">
            <div class="text-xs text-content line-clamp-2">
              {{ image.prompt || image.caption || `${image.width}x${image.height}` }}
            </div>
          </div>
        </MediaImage>
      </div>

      <!-- No images message -->
      <div v-else class="text-sm text-content-muted text-center py-4">
        No images to display
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { MediaImage } from '../media'

interface ImageData {
  media_id: number
  width?: number
  height?: number
  file_format?: string
  prompt?: string
  caption?: string
}

interface DisplayData {
  images: ImageData[]
  count?: number
  tool_name?: string
  description?: string
  source_media_id?: number
}

interface Props {
  itemMetadata: DisplayData | string | null
}

const props = defineProps<Props>()
const emit = defineEmits(['view-image'])

const displayData = computed<DisplayData>(() => {
  if (!props.itemMetadata) {
    return { images: [] }
  }
  if (typeof props.itemMetadata === 'string') {
    try {
      return JSON.parse(props.itemMetadata)
    } catch (e) {
      return { images: [] }
    }
  }
  return props.itemMetadata
})

const images = computed(() => displayData.value.images || [])
const toolName = computed(() => displayData.value.tool_name || null)
const description = computed(() => displayData.value.description || null)
const sourceMediaId = computed(() => displayData.value.source_media_id || null)

// Get all media IDs for slideshow navigation (include source if present)
const mediaIds = computed(() => {
  const ids = images.value.map(img => img.media_id)
  if (sourceMediaId.value) {
    return [sourceMediaId.value, ...ids]
  }
  return ids
})

function formatToolName(name: string): string {
  // Convert snake_case to Title Case
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const gridClass = computed(() => {
  const count = images.value.length
  if (count === 1) return 'grid-cols-1 max-w-[280px]'
  if (count === 2) return 'grid-cols-2 max-w-[400px]'
  if (count <= 4) return 'grid-cols-2 sm:grid-cols-4 max-w-[600px]'
  return 'grid-cols-3 sm:grid-cols-5 max-w-[750px]'
})

function handleImageClick(mediaId: number, index: number) {
  // When source exists, result is at index 1 in mediaIds
  const actualIndex = sourceMediaId.value ? index + 1 : index
  emit('view-image', mediaId, actualIndex, mediaIds.value)
}

function handleSourceClick() {
  if (sourceMediaId.value) {
    emit('view-image', sourceMediaId.value, 0, mediaIds.value)
  }
}
</script>
