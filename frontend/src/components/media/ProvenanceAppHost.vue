<template>
  <slot />

  <!-- An import's raw external metadata -->
  <Modal
    :show="!!rawMetadata"
    size="custom"
    custom-class="w-full max-w-[80vw] h-[80vh] compact:h-[85dvh] flex flex-col overflow-hidden"
    @close="rawMetadata = null"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-content m-0">External metadata</h3>
        <Tooltip text="Close">
          <IconButton aria-label="Close" @click="rawMetadata = null">
            <XMarkIcon class="w-5 h-5" />
          </IconButton>
        </Tooltip>
      </div>
    </template>
    <div class="flex-1 min-h-0">
      <ReadOnlyCode v-if="rawMetadata" :text="rawMetadataDisplay.text" :name="rawMetadataDisplay.name" />
    </div>
  </Modal>

  <!-- Inputs that aren't library media (reference files, preprocessed previews) -->
  <Modal
    :show="!!viewer"
    size="custom"
    custom-class="w-full max-w-[90vw] max-h-[90vh] overflow-hidden"
    @close="viewer = null"
  >
    <div v-if="viewer" class="relative bg-matte">
      <AppImage
        :src="viewer.url"
        :alt="viewer.caption"
        :contain="true"
        background-class="bg-matte"
        container-class="w-full h-[80vh] compact:h-[70dvh]"
      />
      <div class="absolute top-2 right-2">
        <Tooltip text="Close">
          <IconButton aria-label="Close" class="bg-black/55 backdrop-blur-sm !text-white" @click="viewer = null">
            <XMarkIcon class="w-4 h-4" />
          </IconButton>
        </Tooltip>
      </div>
      <div class="px-3 py-2 text-xs text-content-tertiary truncate bg-surface">{{ viewer.caption }}</div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
/**
 * The app's provenance host: provides what the pure "how it was made"
 * components (src/provenance) need inside the app — library thumbnails with
 * drag and context menu, opening and comparing inputs, preprocessed previews,
 * the raw-metadata viewer, and copy with a toast. Wrap any surface that
 * renders provenance components in it.
 */
import { computed, ref } from 'vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import AppImage from './AppImage.vue'
import ProvenanceThumb from './ProvenanceThumb.vue'
import IconButton from '../ui/IconButton.vue'
import Modal from '../ui/Modal.vue'
import Tooltip from '../ui/Tooltip.vue'
import ReadOnlyCode from '../viewers/ReadOnlyCode.vue'
import { preprocessedUrl, referenceFileUrl } from './provenancePreviews'
import { copyToClipboard } from '../../utils/clipboard'
import { addToast } from '../../composables/useToasts'
import { fileBasename, type ProvenanceInput } from '../../utils/mediaProvenance'
import { provideProvenanceHost, type InputAction } from '../../provenance/host'
import type { AppThumbRef } from '../../provenance/fromProvenance'
import type { ViewInput } from '../../provenance/types'

const props = withDefaults(defineProps<{
  /** Offer "Compare" against each library input. */
  allowCompare?: boolean
}>(), {
  allowCompare: false,
})

const emit = defineEmits<{
  (e: 'navigate', mediaId: number): void
  (e: 'compare', mediaId: number): void
}>()

const rawMetadata = ref<string | null>(null)
const rawMetadataDisplay = computed(() => {
  const raw = rawMetadata.value || ''
  try {
    return { text: JSON.stringify(JSON.parse(raw), null, 2), name: 'metadata.json' }
  } catch {
    return { text: raw, name: 'metadata.txt' }
  }
})

const viewer = ref<{ url: string; caption: string } | null>(null)

function source(input: ViewInput): ProvenanceInput {
  return input.origin as ProvenanceInput
}

function processedUrl(input: ViewInput): string {
  const preview = input.preview as AppThumbRef | null
  return preview?.kind === 'preprocessed' ? preprocessedUrl(preview) : ''
}

function canOpenInput(input: ViewInput): boolean {
  const s = source(input)
  return !s.deleted && !!(processedUrl(input) || s.mediaId || s.filePath)
}

function openInput(input: ViewInput) {
  const s = source(input)
  const url = processedUrl(input)
  if (url) {
    viewer.value = { url, caption: 'Preprocessed image' }
  } else if (s.mediaId) {
    emit('navigate', s.mediaId)
  } else if (s.filePath) {
    viewer.value = { url: referenceFileUrl(s.filePath), caption: fileBasename(s.filePath) }
  }
}

function inputActions(input: ViewInput): InputAction[] {
  const s = source(input)
  const actions: InputAction[] = []
  const url = processedUrl(input)
  if (url) {
    actions.push({ label: 'Processed', run: () => { viewer.value = { url, caption: 'Preprocessed image' } } })
    if (s.mediaId) actions.push({ label: 'Original', run: () => emit('navigate', s.mediaId as number) })
  } else if (canOpenInput(input)) {
    actions.push({ label: 'View', run: () => openInput(input) })
  }
  if (s.mediaId && props.allowCompare) {
    actions.push({ label: 'Compare', run: () => emit('compare', s.mediaId as number) })
  }
  return actions
}

provideProvenanceHost({
  thumbnail: ProvenanceThumb,
  tooltip: Tooltip,
  async copy(text) {
    if (await copyToClipboard(text)) addToast('Copied to clipboard', 'success')
    else addToast('Could not copy to clipboard', 'error')
  },
  openInput,
  canOpenInput,
  inputActions,
  openRawMetadata(text) { rawMetadata.value = text },
})
</script>
