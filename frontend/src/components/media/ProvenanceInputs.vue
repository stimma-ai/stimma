<template>
  <div v-if="inputs.length">
    <div class="text-xs text-content-tertiary mb-1.5">Inputs</div>
    <div class="flex flex-wrap gap-3">
      <div v-for="(input, i) in inputs" :key="i" class="flex flex-col">
        <Tooltip :text="inputTitle(input)">
          <button
            type="button"
            class="relative rounded-media overflow-hidden bg-matte p-0 border-none cursor-pointer transition-shadow hover:ring-1 hover:ring-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:cursor-default disabled:hover:ring-0"
            :class="sizeClass"
            :disabled="!canOpen(input)"
            :aria-label="inputTitle(input)"
            @click="openInput(input)"
          >
            <!-- A preprocessed input shows the derived preview, not the library asset. -->
            <AppImage
              v-if="processedUrl(input)"
              :src="processedUrl(input)"
              :alt="input.roleLabel"
              :contain="true"
              background-class="bg-matte"
              container-class="w-full h-full"
            />
            <!-- Library asset: MediaImage so the context menu and drag work like everywhere else. -->
            <MediaImage
              v-else-if="input.mediaId"
              :media-id="input.mediaId"
              :file-path="input.filePath || undefined"
              :alt="input.roleLabel"
              :thumbnail-size="256"
              :contain="true"
              container-class="w-full h-full"
            />
            <AppImage
              v-else-if="input.filePath"
              :src="referenceFileUrl(input.filePath)"
              :alt="input.roleLabel"
              :contain="true"
              background-class="bg-matte"
              container-class="w-full h-full"
            />
            <div v-if="chips(input).length" class="absolute top-1 right-1 flex flex-col gap-0.5 items-end">
              <span
                v-for="chip in chips(input)"
                :key="chip"
                class="px-1.5 py-0.5 rounded-md bg-black/55 backdrop-blur-sm text-white text-[10px] leading-none"
              >{{ chip }}</span>
            </div>
          </button>
        </Tooltip>
        <!-- Actions under the thumbnail: what it was made from, and a compare. -->
        <div class="flex justify-center gap-2 mt-1.5 text-[10px]">
          <template v-if="processedUrl(input)">
            <button type="button" :class="linkClass" @click="openFile(processedUrl(input), 'Preprocessed image')">Processed</button>
            <template v-if="input.mediaId">
              <span class="text-content-muted">|</span>
              <button type="button" :class="linkClass" @click="$emit('navigate', input.mediaId)">Original</button>
            </template>
          </template>
          <button
            v-else-if="canOpen(input)"
            type="button"
            :class="linkClass"
            @click="openInput(input)"
          >View</button>
          <template v-if="input.mediaId && allowCompare">
            <span class="text-content-muted">|</span>
            <button type="button" :class="linkClass" @click="$emit('compare', input.mediaId)">Compare</button>
          </template>
        </div>
      </div>
    </div>

    <!-- Viewer for inputs that aren't library media (reference files, preprocessed previews) -->
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
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import AppImage from './AppImage.vue'
import MediaImage from './MediaImage.vue'
import Modal from '../ui/Modal.vue'
import IconButton from '../ui/IconButton.vue'
import Tooltip from '../ui/Tooltip.vue'
import { getApiBase } from '../../apiConfig'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { fileBasename, type ProvenanceInput } from '../../utils/mediaProvenance'

const props = withDefaults(defineProps<{
  inputs: ProvenanceInput[]
  /** Offer "Compare" against each library input. */
  allowCompare?: boolean
  size?: 'sm' | 'md'
}>(), {
  allowCompare: false,
  size: 'md',
})

const emit = defineEmits<{
  (e: 'navigate', mediaId: number): void
  (e: 'compare', mediaId: number): void
}>()

const linkClass = 'bg-transparent border-none p-0 cursor-pointer text-content-secondary hover:text-content transition-colors duration-150'

const sizeClass = computed(() => (props.size === 'sm' ? 'w-20 h-20' : 'w-24 h-24'))

function chips(input: ProvenanceInput): string[] {
  return [input.preprocessorLabel, ...input.marks].filter((chip): chip is string => !!chip)
}

function inputTitle(input: ProvenanceInput): string {
  return input.preprocessorLabel ? `${input.roleLabel} · ${input.preprocessorLabel}` : input.roleLabel
}

function withAuth(url: string): string {
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  let out = `${url}&profile=${encodeURIComponent(profileId)}`
  if (pin) out += `&pin=${encodeURIComponent(pin)}`
  return out
}

function referenceFileUrl(filePath: string): string {
  return withAuth(`${getApiBase()}/generate/reference-file?path=${encodeURIComponent(filePath)}`)
}

// --- Preprocessed previews ---------------------------------------------------
// A ControlNet-style input ran through a preprocessor; what the tool actually
// saw is the derived image, resolved (and cached) by the backend on demand.

const processed = ref<Record<string, string>>({})

function processedKey(input: ProvenanceInput): string {
  const params = input.preprocessorParams ? JSON.stringify(input.preprocessorParams) : ''
  return `${input.mediaId ?? input.filePath}_${input.preprocessor}_${params}`
}

function processedUrl(input: ProvenanceInput): string {
  return input.preprocessor ? processed.value[processedKey(input)] || '' : ''
}

async function resolveProcessed(input: ProvenanceInput) {
  const key = processedKey(input)
  if (processed.value[key]) return
  try {
    const resp = await axios.post(`${getApiBase()}/generate/preprocess-controlnet`, {
      source_path: input.filePath,
      preprocessor: input.preprocessor,
      preprocessor_params: input.preprocessorParams || null,
    })
    if (resp.data?.path) {
      const url = withAuth(`${getApiBase()}/generate/controlnet-preview?path=${encodeURIComponent(resp.data.path)}`)
      processed.value = { ...processed.value, [key]: url }
    }
  } catch (err) {
    console.warn('Failed to resolve preprocessed image:', err)
  }
}

watch(() => props.inputs, (inputs) => {
  for (const input of inputs) {
    if (input.preprocessor && input.filePath) void resolveProcessed(input)
  }
}, { immediate: true })

// --- Opening -------------------------------------------------------------------

const viewer = ref<{ url: string; caption: string } | null>(null)

function canOpen(input: ProvenanceInput): boolean {
  return !input.deleted && !!(processedUrl(input) || input.mediaId || input.filePath)
}

function openFile(url: string, caption: string) {
  viewer.value = { url, caption }
}

function openInput(input: ProvenanceInput) {
  const url = processedUrl(input)
  if (url) return openFile(url, 'Preprocessed image')
  if (input.mediaId) return emit('navigate', input.mediaId)
  if (input.filePath) openFile(referenceFileUrl(input.filePath), fileBasename(input.filePath))
}
</script>
