<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="modelValue"
        class="fixed inset-0 z-modal flex items-center justify-center p-8"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-overlay-backdrop"
          @click="close"
        />

        <!-- Modal content -->
        <div
          class="relative w-full h-full max-w-[95vw] max-h-[95vh] bg-surface rounded-lg border border-surface-raised flex flex-col overflow-hidden"
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-4 py-3 border-b border-surface-raised">
            <h2 class="text-sm font-medium text-content-secondary">Edit Mask</h2>
            <button
              @click="close"
              class="p-1 rounded text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
            >
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Mask editor in modal mode -->
          <div class="flex-1 overflow-hidden p-4 min-h-0 flex flex-col">
            <MaskEditor
              ref="maskEditorRef"
              :image="image"
              :model-value="maskDataUrl"
              :mask-format="maskFormat"
              :modal-mode="true"
              @update:model-value="handleMaskUpdate"
              @update:image="$emit('update:image', $event)"
            />
          </div>

          <!-- AI Mask Assistant -->
          <div v-if="image?.path" class="px-4 pb-4 flex-shrink-0">
            <AIMaskAssistant
              :image-path="image.path"
              :mask-editor-ref="maskEditorRef"
            />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import MaskEditor from './MaskEditor.vue'
import AIMaskAssistant from './AIMaskAssistant.vue'
import type { MaskFormat } from '../../composables/useToolSchemaFeatures'

interface ImageInfo {
  path: string
  filename?: string
  hash?: string
  mediaId?: number
  width?: number
  height?: number
}

interface Props {
  modelValue: boolean // open/closed state
  image?: ImageInfo | null
  maskDataUrl?: string | null
  maskFormat?: MaskFormat
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'update:maskDataUrl', value: string | null): void
  (e: 'update:image', value: ImageInfo | null): void
}>()

const maskEditorRef = ref<InstanceType<typeof MaskEditor> | null>(null)

function close() {
  emit('update:modelValue', false)
}

function handleMaskUpdate(value: string | null) {
  emit('update:maskDataUrl', value)
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

// Prevent body scroll when modal is open
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})

// Expose the mask editor ref for external access
defineExpose({
  maskEditorRef
})
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
