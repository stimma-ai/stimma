<script setup lang="ts">
import { computed, ref } from 'vue'
import axios from 'axios'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  PlusIcon,
  TrashIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import MediaImage from '../../components/media/MediaImage.vue'
import MediaPickerPopover from '../../components/generation/MediaPickerPopover.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { addToast } from '../../composables/useToasts'
import { useOwnerProject } from '../../composables/useProjectScope'
import { appendProjectId } from '../../utils/projectScope'
import type { ModelReferenceImage } from '../stack/types'

const props = withDefaults(defineProps<{
  modelValue?: ModelReferenceImage[]
  minItems?: number
  maxItems: number
  disabled?: boolean
  /**
   * Compact in-field variant: small thumbs + a quiet add chip, living INSIDE
   * the prompt field like a chat attachment. The block variant (default) is
   * the inspector's thumbnail workspace with reorder controls.
   */
  inline?: boolean
}>(), {
  modelValue: () => [],
  minItems: 0,
  disabled: false,
  inline: false,
})

const emit = defineEmits<{
  'update:modelValue': [ModelReferenceImage[]]
}>()

const { getMediaItem } = useMediaApi()
const addButton = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const pickerOpen = ref(false)
const uploading = ref(false)

const items = computed(() => props.modelValue ?? [])
const overCapacity = computed(() => items.value.length > props.maxItems)
const belowMinimum = computed(() => items.value.length < props.minItems)

function update(next: ModelReferenceImage[]) {
  emit('update:modelValue', next)
}

function remove(index: number) {
  update(items.value.filter((_, itemIndex) => itemIndex !== index))
}

function move(index: number, offset: -1 | 1) {
  const nextIndex = index + offset
  if (nextIndex < 0 || nextIndex >= items.value.length) return
  const next = [...items.value]
  ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
  update(next)
}

async function addFromMediaId(mediaId: number) {
  if (props.disabled || items.value.length >= props.maxItems) return
  pickerOpen.value = false
  try {
    const media = await getMediaItem(mediaId)
    update([
      ...items.value,
      {
        media_id: media.id,
        file_hash: media.file_hash,
        filename: media.file_name
          ?? media.filename
          ?? media.file_path?.split('/').pop(),
      },
    ])
  } catch (error: any) {
    addToast(error?.response?.data?.detail || 'Could not add that reference image.', 'error')
  }
}

function browse() {
  pickerOpen.value = false
  fileInput.value?.click()
}

// Uploaded references become assets in the editor's active project.
const uploadProjectId = useOwnerProject()

async function uploadFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])].slice(0, Math.max(0, props.maxItems - items.value.length))
  input.value = ''
  if (!files.length) return

  uploading.value = true
  try {
    const added: ModelReferenceImage[] = []
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      appendProjectId(form, uploadProjectId.value)
      const { data } = await axios.post('/api/generate/upload-reference', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      added.push({
        media_id: data.media_id,
        file_hash: data.file_hash,
        filename: data.filename || file.name,
      })
    }
    update([...items.value, ...added])
  } catch (error: any) {
    addToast(error?.response?.data?.detail || 'Could not upload that reference image.', 'error')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div
    :class="inline
      ? 'flex items-center gap-1.5 flex-none'
      : ['border-t border-edge-subtle', items.length ? 'px-3 py-1.5 bg-overlay-faint' : 'px-2 py-1']"
  >
    <!-- Inline: attachment chips inside the prompt field. -->
    <template v-if="inline">
      <div
        v-for="(item, index) in items"
        :key="`${item.media_id}:${index}`"
        class="group/reference relative flex-none w-6 h-6 rounded-media overflow-hidden bg-matte"
        :title="item.filename || `Reference ${index + 1}`"
      >
        <MediaImage
          :media-id="item.media_id"
          :file-hash="item.file_hash"
          :thumbnail="true"
          :thumbnail-size="64"
          :draggable="false"
          :enable-context-menu="false"
          container-class="w-full h-full"
          img-class="w-full h-full object-cover"
        />
        <button
          type="button"
          class="absolute inset-0 grid place-items-center bg-black/60 text-white
                 opacity-0 group-hover/reference:opacity-100 focus-visible:opacity-100
                 transition-opacity disabled:opacity-0"
          :disabled="disabled"
          aria-label="Remove reference"
          @click="remove(index)"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
      </div>
      <button
        v-if="items.length < maxItems"
        ref="addButton"
        type="button"
        class="grid h-6 w-6 flex-none place-items-center rounded-md
               transition-colors disabled:opacity-40"
        :class="belowMinimum
          ? 'text-amber-400 hover:text-amber-300'
          : 'text-content-tertiary hover:text-content-secondary hover:bg-overlay-subtle'"
        :disabled="disabled || uploading"
        aria-label="Add reference image"
        :title="uploading
          ? 'Adding…'
          : belowMinimum ? 'Add required reference image' : 'Add reference image'"
        @click="pickerOpen = true"
      >
        <PlusIcon class="w-3.5 h-3.5" />
      </button>
      <span
        v-if="overCapacity"
        class="text-[10px] font-mono tabular-nums text-amber-400"
        :title="`This model accepts ${maxItems} reference image${maxItems === 1 ? '' : 's'}. Remove extras to run.`"
      >
        {{ items.length }}/{{ maxItems }}
      </span>
    </template>

    <!-- Optional references start as one quiet affordance. The thumbnail
         workspace does not claim compose space until somebody opts into it. -->
    <button
      v-else-if="items.length === 0"
      ref="addButton"
      type="button"
      class="inline-flex items-center gap-1.5 px-2 py-1 text-[11px] rounded-md
             text-content-tertiary hover:text-content-secondary hover:bg-overlay-subtle
             transition-colors disabled:opacity-40"
      :class="belowMinimum ? 'text-amber-400 hover:text-amber-300' : ''"
      :disabled="disabled || uploading"
      @click="pickerOpen = true"
    >
      <PlusIcon class="w-3 h-3" />
      {{ belowMinimum ? 'Add required reference' : 'Add reference' }}
      <span v-if="uploading" class="text-content-tertiary">Adding…</span>
    </button>

    <template v-else>
      <div class="flex items-center gap-2">
        <span class="text-[11px] font-medium text-content-secondary">References</span>
        <span class="text-[10px] font-mono tabular-nums text-content-tertiary">
          {{ items.length }}/{{ maxItems }}
        </span>
        <span v-if="uploading" class="text-[10px] text-content-tertiary">Adding…</span>
      </div>

      <div class="mt-1 flex items-center gap-1.5 overflow-x-auto">
        <div
          v-for="(item, index) in items"
          :key="`${item.media_id}:${index}`"
          class="group/reference relative flex-none w-12 h-12 rounded-media overflow-hidden
                 border border-edge-subtle bg-matte"
          :title="item.filename || `Reference ${index + 1}`"
        >
          <MediaImage
            :media-id="item.media_id"
            :file-hash="item.file_hash"
            :thumbnail="true"
            :thumbnail-size="128"
            :draggable="false"
            :enable-context-menu="false"
            container-class="w-full h-full"
            img-class="w-full h-full object-cover"
          />
          <span
            class="absolute top-1 left-1 min-w-4 h-4 px-1 rounded-sm bg-black/70
                   text-[9px] leading-4 text-white text-center font-mono"
          >
            {{ index + 1 }}
          </span>
          <div
            class="absolute inset-x-0 bottom-0 flex justify-end bg-gradient-to-t from-black/80 to-transparent
                   opacity-0 group-hover/reference:opacity-100 focus-within:opacity-100 transition-opacity"
          >
            <button
              type="button"
              class="p-1 text-white/80 hover:text-white disabled:opacity-30"
              :disabled="disabled || index === 0"
              aria-label="Move reference left"
              @click="move(index, -1)"
            >
              <ArrowLeftIcon class="w-3 h-3" />
            </button>
            <button
              type="button"
              class="p-1 text-white/80 hover:text-white disabled:opacity-30"
              :disabled="disabled || index === items.length - 1"
              aria-label="Move reference right"
              @click="move(index, 1)"
            >
              <ArrowRightIcon class="w-3 h-3" />
            </button>
            <button
              type="button"
              class="p-1 text-white/80 hover:text-red-300 disabled:opacity-30"
              :disabled="disabled"
              aria-label="Remove reference"
              @click="remove(index)"
            >
              <TrashIcon class="w-3 h-3" />
            </button>
          </div>
        </div>

        <button
          v-if="items.length < maxItems"
          ref="addButton"
          type="button"
          class="flex-none w-12 h-12 rounded-media border border-dashed border-edge-strong
                 text-content-tertiary hover:text-accent-hi hover:border-accent
                 flex items-center justify-center transition-colors disabled:opacity-40"
          :disabled="disabled || uploading"
          aria-label="Add reference image"
          @click="pickerOpen = true"
        >
          <PlusIcon class="w-4 h-4" />
        </button>
      </div>
    </template>

    <template v-if="!inline && items.length">
      <p v-if="overCapacity" class="mt-1 text-[10px] text-amber-400">
        This model accepts {{ maxItems }} reference image{{ maxItems === 1 ? '' : 's' }}. Remove extras to run.
      </p>
      <p v-else-if="belowMinimum" class="mt-1 text-[10px] text-amber-400">
        Add at least {{ minItems }} reference image{{ minItems === 1 ? '' : 's' }}.
      </p>
    </template>

    <input
      ref="fileInput"
      type="file"
      accept="image/*"
      :multiple="maxItems - items.length > 1"
      class="hidden"
      @change="uploadFiles"
    >
    <MediaPickerPopover
      v-if="pickerOpen"
      accept="image"
      :anchor-el="addButton"
      :exclude-ids="items.map(item => item.media_id)"
      :allow-video-frames="false"
      :show-drop-hint="false"
      @pick="addFromMediaId"
      @browse="browse"
      @close="pickerOpen = false"
    />
  </div>
</template>
