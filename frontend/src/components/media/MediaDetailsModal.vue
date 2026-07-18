<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-100"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="mediaDetails.state.value.visible"
        class="fixed inset-0 z-modal flex items-center justify-center p-6"
        @click.self="mediaDetails.close()"
      >
        <div class="absolute inset-0 bg-overlay-backdrop backdrop-blur-sm" @click="mediaDetails.close()" />

        <div class="relative bg-surface border border-edge-subtle rounded-lg shadow-2xl overflow-hidden flex" style="width: 1100px; height: 75vh">
          <!-- Close -->
          <button
            class="absolute top-3 right-3 z-10 w-8 h-8 flex items-center justify-center rounded-full bg-overlay-strong text-content-tertiary hover:text-content hover:bg-overlay-medium transition-colors"
            @click="mediaDetails.close()"
            title="Close (Esc)"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>

          <ImageDetailsCard
            v-if="media"
            :media="media"
            @navigate="navigateTo"
            @open-flow="openFlow"
          />
          <div v-else class="w-full h-full flex items-center justify-center">
            <span class="text-content-tertiary text-sm animate-pulse">{{ error || 'Loading…' }}</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaDetailsModal } from '../../composables/useMediaDetailsModal'
import { useMediaApi } from '../../composables/useMediaApi'
import ImageDetailsCard from './ImageDetailsCard.vue'

const router = useRouter()
const mediaDetails = useMediaDetailsModal()
const { getMediaItem } = useMediaApi()

const media = ref(null)
const error = ref(null)
const currentMediaId = ref(null)
let loadToken = 0

async function loadMedia(id) {
  media.value = null
  error.value = null
  currentMediaId.value = id
  if (!id) return
  const token = ++loadToken
  try {
    const item = await getMediaItem(id, { includeTrashed: true })
    if (token !== loadToken) return
    media.value = item
  } catch (err) {
    if (token !== loadToken) return
    error.value = err?.response?.status === 404 ? 'Media item not found' : 'Failed to load details'
  }
}

function navigateTo(id) {
  loadMedia(id)
}

function openFlow(flowId) {
  mediaDetails.close()
  router.push({ name: 'flow', params: { id: String(flowId) } })
}

watch(
  () => mediaDetails.state.value.visible ? mediaDetails.state.value.mediaId : null,
  (id) => {
    if (id) loadMedia(id)
    else { media.value = null; error.value = null; currentMediaId.value = null }
  },
  { immediate: true }
)

function handleKeydown(e) {
  if (!mediaDetails.state.value.visible) return
  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    mediaDetails.close()
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown, true))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown, true))
</script>
