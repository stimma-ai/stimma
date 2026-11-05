<template>
  <div class="relative">
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      :disabled="disabled"
      class="flex items-center gap-2 px-2.5 py-2 rounded-md text-content-secondary text-sm hover:bg-overlay-subtle hover:text-content transition-colors duration-150 whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <!-- Aspect ratio preview rectangle -->
      <span
        class="border border-edge bg-surface-raised flex-shrink-0"
        :style="aspectPreviewStyle"
      ></span>
      <span>{{ displayText }}</span>
      <!-- Dropdown caret -->
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" class="w-icon-inline h-icon-inline text-content-muted">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <div
      v-if="showDropdown"
      class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu p-3 space-y-3"
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
            'px-2 py-1 rounded-md text-xs font-medium transition-colors duration-150',
            aspectRatio === ar
              ? 'bg-accent text-accent-on'
              : 'bg-overlay-subtle text-content-tertiary hover:bg-overlay-light'
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
            'px-2 py-1 rounded-md text-xs font-medium transition-colors duration-150',
            aspectRatio === ar
              ? 'bg-accent text-accent-on'
              : 'bg-overlay-subtle text-content-tertiary hover:bg-overlay-light'
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
              'px-2 py-1 rounded-md text-xs font-medium transition-colors duration-150',
              imageSize === size
                ? 'bg-accent text-accent-on'
                : 'bg-overlay-subtle text-content-tertiary hover:bg-overlay-light'
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
