<template>
  <div class="flex items-center justify-between mb-6">
    <h2 class="text-2xl font-semibold text-content">
      <slot name="title">Generate</slot>
    </h2>

    <div class="flex gap-2 items-center">
      <!-- Generate Button -->
      <button
        @click="$emit('submit')"
        :disabled="!canSubmit || isSubmitting"
        class="px-4 py-3 bg-blue-500 rounded-lg text-white text-base font-semibold cursor-pointer transition-colors disabled:bg-[#1a2a3a] disabled:cursor-not-allowed disabled:opacity-50 hover:bg-blue-600 flex items-center justify-center gap-2"
      >
        <span v-if="isSubmitting">Submitting...</span>
        <template v-else>
          <span>{{ submitLabel }}</span>
          <span v-if="shortcutDisplay" class="text-sm opacity-70 font-normal">{{ shortcutDisplay }}</span>
        </template>
      </button>

      <!-- Forever Mode Toggle (optional) -->
      <button
        v-if="showForeverMode"
        @click="$emit('toggle-forever')"
        :class="[
          'px-4 py-3 rounded-lg text-base font-semibold cursor-pointer transition-colors flex items-center justify-center gap-2',
          foreverMode ? 'bg-pink-500 text-white hover:bg-pink-600' : 'bg-surface-raised text-content hover:bg-surface-hover'
        ]"
        :title="foreverMode ? 'Forever mode active - click to stop' : 'Enable forever mode'"
      >
        <span>∞</span>
      </button>

      <!-- Separator (only if forever mode is shown) -->
      <div v-if="showForeverMode" class="w-px bg-surface-hover my-1"></div>

      <!-- Auto-delete duration selector -->
      <AutoDeletePicker
        :model-value="autoDeleteDuration"
        @update:model-value="setAutoDeleteDuration"
      />

      <!-- Options Menu -->
      <div class="relative">
        <button
          @click="showOptionsMenu = !showOptionsMenu"
          class="p-2 hover:bg-overlay-light rounded transition-colors"
          title="Options"
        >
          <svg class="w-5 h-5 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
          </svg>
        </button>
        <Transition name="fade">
          <div
            v-if="showOptionsMenu"
            class="absolute right-0 top-10 z-50"
            @click.stop
          >
            <ToolMenu
              v-if="showToolOptions"
              :pinned="toolPinned"
              :show-reset-defaults="true"
              @rename="handleRename"
              @toggle-pin="handleTogglePin"
              @duplicate="handleDuplicate"
              @delete="handleDelete"
              @reset-defaults="handleRevertDefaults"
            />
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import AutoDeletePicker from '../AutoDeletePicker.vue'
import ToolMenu from '../ToolMenu.vue'
import { useToolAutoDeleteDuration } from '../../composables/useToolAutoDeleteDuration'

interface Props {
  canSubmit: boolean
  isSubmitting: boolean
  submitLabel?: string
  showForeverMode?: boolean
  foreverMode?: boolean
  // Tool-specific options (optional, for ToolView)
  showToolOptions?: boolean
  toolPinned?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  submitLabel: 'Generate',
  showForeverMode: false,
  foreverMode: false,
  showToolOptions: false,
  toolPinned: false
})

const emit = defineEmits<{
  (e: 'submit'): void
  (e: 'toggle-forever'): void
  (e: 'revert-defaults'): void
  (e: 'rename'): void
  (e: 'toggle-pin'): void
  (e: 'duplicate'): void
  (e: 'delete'): void
}>()

// Use shared auto-delete duration
const { autoDeleteDuration, setAutoDeleteDuration } = useToolAutoDeleteDuration()

// Options menu state
const showOptionsMenu = ref(false)

function handleRevertDefaults() {
  showOptionsMenu.value = false
  emit('revert-defaults')
}

function handleRename() {
  showOptionsMenu.value = false
  emit('rename')
}

function handleTogglePin() {
  showOptionsMenu.value = false
  emit('toggle-pin')
}

function handleDuplicate() {
  showOptionsMenu.value = false
  emit('duplicate')
}

function handleDelete() {
  showOptionsMenu.value = false
  emit('delete')
}

// Close menu when clicking outside
function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!target.closest('.relative')) {
    showOptionsMenu.value = false
  }
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
})

// OS Detection for keyboard shortcuts
const isMac = computed(() => {
  return typeof navigator !== 'undefined' && navigator.platform.toUpperCase().indexOf('MAC') >= 0
})

const isMobile = computed(() => {
  return typeof navigator !== 'undefined' && /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
})

const shortcutDisplay = computed(() => {
  if (isMobile.value) return ''
  return isMac.value ? '⌘↵' : 'Ctrl+↵'
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
