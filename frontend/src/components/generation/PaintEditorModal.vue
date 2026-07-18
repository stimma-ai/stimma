<template>
  <Modal
    :show="modelValue"
    size="custom"
    custom-class="w-full h-full max-w-[1400px] max-h-[900px] flex flex-col overflow-hidden"
    @close="close"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-medium text-content">Edit Input Image</h3>
        <IconButton @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

    <!-- Editor fills remaining space -->
    <PaintEditor
      class="flex-1 min-h-0"
      :image="image"
      :paint-layer-data-url="paintLayerDataUrl"
      @update:paint-layer-data-url="$emit('update:paintLayerDataUrl', $event)"
      @done="close"
    />
  </Modal>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import Modal from '../ui/Modal.vue'
import IconButton from '../ui/IconButton.vue'
import PaintEditor from './PaintEditor.vue'

interface ImageInfo {
  path: string
  hash?: string
  mediaId?: number
  width?: number
  height?: number
}

interface Props {
  modelValue: boolean
  image: ImageInfo | null
  paintLayerDataUrl: string | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'update:paintLayerDataUrl', value: string | null): void
}>()

function close() {
  emit('update:modelValue', false)
}

// Prevent body scroll when open
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})
</script>
