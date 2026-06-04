<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <div v-if="modelValue" class="fixed inset-0 z-[10001] flex items-center justify-center bg-black/60 p-6">
      <!-- Modal card -->
      <div class="flex flex-col w-full h-full max-w-[1400px] max-h-[900px] bg-surface rounded-xl border border-edge-subtle shadow-2xl overflow-hidden">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-2 border-b border-edge-subtle flex-shrink-0">
          <h3 class="text-sm font-medium text-content">Edit Input Image</h3>
          <button
            @click="close"
            class="p-1 rounded text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Editor fills remaining space -->
        <PaintEditor
          class="flex-1 min-h-0"
          :image="image"
          :paint-layer-data-url="paintLayerDataUrl"
          @update:paint-layer-data-url="$emit('update:paintLayerDataUrl', $event)"
          @done="close"
        />
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { watch, onMounted, onUnmounted } from 'vue'
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

// Handle escape key
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.modelValue) {
    close()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})

// Prevent body scroll when open
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})
</script>
