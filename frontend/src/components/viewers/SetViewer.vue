<template>
  <div class="w-full h-full bg-slideshow-matt flex flex-col">
    <!-- Header -->
    <div class="flex items-center gap-4 p-4 border-b border-edge-subtle">
      <button
        @click="$emit('back')"
        class="flex items-center gap-2 text-content-secondary hover:text-content transition-colors"
      >
        <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
        </svg>
        Back
      </button>

      <div class="flex-1">
        <h1 v-if="title" class="text-lg font-semibold text-content">{{ title }}</h1>
        <p v-if="description" class="text-sm text-content-tertiary">{{ description }}</p>
      </div>

      <div class="text-sm text-content-tertiary">
        {{ currentIndex + 1 }} / {{ items.length }}
      </div>
    </div>

    <!-- Main content area -->
    <div class="flex-1 relative overflow-hidden">
      <div v-if="loading" class="flex items-center justify-center h-full text-content-tertiary">
        Loading set...
      </div>

      <div v-else-if="error" class="flex items-center justify-center h-full text-red-500">
        {{ error }}
      </div>

      <div v-else-if="items.length === 0" class="flex items-center justify-center h-full text-content-tertiary">
        This set is empty
      </div>

      <!-- Current item display -->
      <div v-else class="w-full h-full flex items-center justify-center">
        <div v-if="currentResolvedItem" class="relative w-full h-full">
          <img
            :src="getThumbnailUrl(currentResolvedItem.file_hash)"
            :alt="currentResolvedItem.vlm_caption || 'Set item'"
            class="w-full h-full object-contain"
          />

          <!-- Caption overlay -->
          <div v-if="currentCaption" class="absolute bottom-0 left-0 right-0 bg-overlay-strong px-4 py-2 text-content text-sm">
            {{ currentCaption }}
          </div>
        </div>

        <div v-else class="flex flex-col items-center justify-center text-content-muted">
          <svg class="w-16 h-16 mb-2" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <span>Item not found in library</span>
        </div>
      </div>

      <!-- Navigation buttons -->
      <button
        v-if="currentIndex > 0"
        @click="previous"
        class="absolute left-4 top-1/2 -translate-y-1/2 w-12 h-12 rounded-full bg-black/70 hover:bg-black/50 text-white flex items-center justify-center transition-colors"
      >
        <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
        </svg>
      </button>

      <button
        v-if="currentIndex < items.length - 1"
        @click="next"
        class="absolute right-4 top-1/2 -translate-y-1/2 w-12 h-12 rounded-full bg-black/70 hover:bg-black/50 text-white flex items-center justify-center transition-colors"
      >
        <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
      </button>
    </div>

    <!-- Thumbnail strip -->
    <div class="h-20 border-t border-edge-subtle flex items-center gap-2 px-4 overflow-x-auto">
      <button
        v-for="(item, idx) in items"
        :key="idx"
        @click="currentIndex = idx"
        :class="[
          'flex-shrink-0 w-16 h-16 rounded overflow-hidden border-2 transition-all',
          currentIndex === idx ? 'border-blue-500' : 'border-transparent hover:border-edge-strong'
        ]"
      >
        <img
          v-if="item.resolved"
          :src="getThumbnailUrl(item.resolved.file_hash, 64)"
          class="w-full h-full object-cover"
        />
        <div v-else class="w-full h-full bg-surface flex items-center justify-center">
          <svg class="w-6 h-6 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useMediaApi } from '../../composables/useMediaApi'
import axios from 'axios'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['back'])

const { getThumbnailUrl } = useMediaApi()

const loading = ref(true)
const error = ref(null)
const title = ref('')
const description = ref('')
const items = ref([])
const currentIndex = ref(0)

const currentResolvedItem = computed(() => {
  const item = items.value[currentIndex.value]
  return item?.resolved || null
})

const currentCaption = computed(() => {
  return items.value[currentIndex.value]?.caption || ''
})

async function loadContent() {
  loading.value = true
  error.value = null

  try {
    const response = await axios.get(`/api/media/${props.mediaId}/content`)
    const data = response.data

    title.value = data.title || ''
    description.value = data.description || ''
    items.value = data.items || []
  } catch (e) {
    console.error('Failed to load set content:', e)
    error.value = 'Failed to load set content'
  } finally {
    loading.value = false
  }
}

function previous() {
  if (currentIndex.value > 0) {
    currentIndex.value--
  }
}

function next() {
  if (currentIndex.value < items.value.length - 1) {
    currentIndex.value++
  }
}

// Keyboard navigation
function handleKeydown(e) {
  if (e.key === 'ArrowLeft' || e.key === 'a') {
    previous()
  } else if (e.key === 'ArrowRight' || e.key === 'd') {
    next()
  } else if (e.key === 'Escape') {
    emit('back')
  }
}

onMounted(() => {
  loadContent()
  window.addEventListener('keydown', handleKeydown)
})

import { onUnmounted } from 'vue'
onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})

watch(() => props.mediaId, loadContent)
</script>
