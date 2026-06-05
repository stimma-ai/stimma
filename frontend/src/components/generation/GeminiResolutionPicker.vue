<template>
  <div class="relative">
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      :disabled="disabled"
      class="flex items-center gap-2 px-3 py-2 bg-surface border border-surface-raised rounded-md text-content-secondary text-sm hover:bg-surface-raised transition-colors whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <!-- Aspect ratio preview rectangle -->
      <span
        class="border border-[#6b7280] bg-surface-raised flex-shrink-0"
        :style="aspectPreviewStyle"
      ></span>
      <span>{{ displayText }}</span>
      <!-- Dropdown caret -->
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <div
      v-if="showDropdown"
      class="fixed bg-surface border border-surface-raised rounded-lg shadow-lg z-[9999] p-3 space-y-3"
      :style="dropdownStyle"
      @click.stop
    >
      <!-- Aspect Ratio Buttons - Row 1 (portrait/square) -->
      <div class="flex gap-1 flex-wrap">
        <button
          v-for="ar in aspectRatiosRow1"
          :key="ar"
          @click="selectAspectRatio(ar)"
          :class="[
            'px-2 py-1 rounded text-xs font-medium transition-colors',
            aspectRatio === ar
              ? 'bg-blue-500 text-white'
              : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised'
          ]"
        >
          {{ ar }}
        </button>
      </div>

      <!-- Aspect Ratio Buttons - Row 2 (landscape) -->
      <div class="flex gap-1 flex-wrap">
        <button
          v-for="ar in aspectRatiosRow2"
          :key="ar"
          @click="selectAspectRatio(ar)"
          :class="[
            'px-2 py-1 rounded text-xs font-medium transition-colors',
            aspectRatio === ar
              ? 'bg-blue-500 text-white'
              : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised'
          ]"
        >
          {{ ar }}
        </button>
      </div>

      <!-- Image Size Selector -->
      <div v-if="imageSizeChoices.length > 1" class="flex items-center gap-2">
        <span class="text-xs text-content-muted">Size:</span>
        <div class="flex gap-1">
          <button
            v-for="size in imageSizeChoices"
            :key="size"
            @click="selectImageSize(size)"
            :class="[
              'px-2 py-1 rounded text-xs font-medium transition-colors',
              imageSize === size
                ? 'bg-blue-500 text-white'
                : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised'
            ]"
          >
            {{ size }}
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface Props {
  aspectRatio: string
  imageSize: string
  imageSizeChoices?: string[]
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  aspectRatio: '1:1',
  imageSize: '1K',
  imageSizeChoices: () => ['1K', '2K', '4K'],
  disabled: false
})

const emit = defineEmits<{
  (e: 'update:aspectRatio', value: string): void
  (e: 'update:imageSize', value: string): void
}>()

const showDropdown = ref(false)
const buttonRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref({})

// Split aspect ratios into two rows for better layout
const aspectRatiosRow1 = ['9:16', '2:3', '3:4', '4:5', '1:1']
const aspectRatiosRow2 = ['5:4', '4:3', '3:2', '16:9', '21:9']

// Compute display text
const displayText = computed(() => {
  if (props.imageSizeChoices.length > 1) {
    return `${props.aspectRatio} · ${props.imageSize}`
  }
  return props.aspectRatio
})

// Aspect ratio preview rectangle style
const aspectPreviewStyle = computed(() => {
  const parts = props.aspectRatio.split(':')
  const w = parseInt(parts[0])
  const h = parseInt(parts[1])
  const maxSize = 16 // max dimension in pixels

  if (w >= h) {
    // Landscape or square
    return {
      width: `${maxSize}px`,
      height: `${Math.round((h / w) * maxSize)}px`
    }
  } else {
    // Portrait
    return {
      width: `${Math.round((w / h) * maxSize)}px`,
      height: `${maxSize}px`
    }
  }
})

function toggleDropdown() {
  if (props.disabled) return

  if (!showDropdown.value && buttonRef.value) {
    const rect = buttonRef.value.getBoundingClientRect()
    const dropdownWidth = 260 // Approximate dropdown width
    const viewportWidth = window.innerWidth
    const padding = 16

    // Check if dropdown would overflow right edge
    let left = rect.left
    if (left + dropdownWidth > viewportWidth - padding) {
      // Align to right edge of button instead
      left = Math.max(padding, rect.right - dropdownWidth)
    }

    dropdownStyle.value = {
      top: `${rect.bottom + 4}px`,
      left: `${left}px`
    }
  }
  showDropdown.value = !showDropdown.value
}

function selectAspectRatio(ar: string) {
  emit('update:aspectRatio', ar)
}

function selectImageSize(size: string) {
  emit('update:imageSize', size)
}

// Close dropdown when clicking outside
function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element
  if (showDropdown.value && buttonRef.value && !buttonRef.value.contains(target)) {
    showDropdown.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
