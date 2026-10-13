<template>
  <Modal
    :show="mediaDetails.state.value.visible"
    size="custom"
    custom-class="relative w-full max-w-[1100px] h-[75vh] flex overflow-hidden compact:h-auto compact:block compact:overflow-y-auto"
    :close-on-esc="false"
    @close="mediaDetails.close()"
  >
    <div class="absolute top-3 right-3 z-chrome">
      <Tooltip text="Close">
        <IconButton aria-label="Close" class="bg-overlay-strong" @click="mediaDetails.close()">
          <XMarkIcon class="w-4 h-4" />
        </IconButton>
      </Tooltip>
    </div>

    <ImageDetailsCard
      v-if="media"
      :media="media"
      @navigate="navigateTo"
      @open-flow="openFlow"
    />
    <div v-else class="w-full h-full min-h-48 flex items-center justify-center gap-2 text-content-tertiary text-sm">
      <Spinner v-if="!error" size="sm" />
      <span>{{ error || 'Loading…' }}</span>
    </div>
  </Modal>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaDetailsModal } from '../../composables/useMediaDetailsModal'
import { useMediaApi } from '../../composables/useMediaApi'
import ImageDetailsCard from './ImageDetailsCard.vue'
import Modal from '../ui/Modal.vue'
import IconButton from '../ui/IconButton.vue'
import Spinner from '../ui/Spinner.vue'
import Tooltip from '../ui/Tooltip.vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'

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
