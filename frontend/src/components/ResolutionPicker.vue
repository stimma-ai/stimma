<template>
  <div class="relative">
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      :disabled="disabled"
      :class="[
        'flex items-center gap-2 font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
        compact
          ? 'px-2.5 h-7 rounded text-xs text-content-tertiary hover:text-content hover:bg-surface'
          : 'px-3 h-10 rounded-lg border border-edge-subtle bg-overlay-subtle text-sm text-content-tertiary hover:bg-overlay-light hover:text-content'
      ]"
    >
      <!-- Aspect ratio preview rectangle -->
      <span
        class="border border-edge bg-surface-raised flex-shrink-0"
        :style="aspectPreviewStyle"
      ></span>
      <span>{{ resolutionSummary }}</span>
      <svg
        v-if="lockSize || lockArea"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        class="w-3.5 h-3.5 text-blue-500"
      >
        <path fill-rule="evenodd" d="M10 1.944a4 4 0 0 0-4 4V8H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-1V5.944a4 4 0 0 0-4-4ZM8 8V5.944a2 2 0 1 1 4 0V8H8Z" clip-rule="evenodd" />
      </svg>
      <!-- Dropdown caret -->
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" :class="compact ? 'w-3 h-3 text-content-muted' : 'w-4 h-4 text-content-muted'">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <div
      v-if="showDropdown"
      class="fixed bg-surface border border-edge rounded-lg shadow-xl z-[9999] p-3 space-y-3"
      :style="dropdownStyle"
      @click.stop
    >
      <!-- Mode Switcher -->
      <div class="flex bg-base rounded p-0.5 gap-0.5">
        <button
          @click="mode = 'aspect'"
          :class="[
            'flex-1 px-2 py-1 rounded text-xs font-medium transition-colors',
            mode === 'aspect'
              ? 'bg-surface-raised text-content'
              : 'text-content-muted hover:text-content-secondary'
          ]"
        >Aspect</button>
        <button
          @click="mode = 'manual'"
          :class="[
            'flex-1 px-2 py-1 rounded text-xs font-medium transition-colors',
            mode === 'manual'
              ? 'bg-surface-raised text-content'
              : 'text-content-muted hover:text-content-secondary'
          ]"
        >Manual</button>
      </div>

      <!-- Aspect Ratio Mode -->
      <template v-if="mode === 'aspect'">
        <!-- Aspect Ratio Buttons -->
        <div class="flex gap-1">
          <button
            v-for="ar in aspectRatios"
            :key="ar.label"
            @click="selectAspectRatio(ar.label)"
            :class="[
              'px-2 py-1 rounded text-xs font-medium transition-colors',
              selectedAspectRatio === ar.label
                ? 'bg-blue-500/20 text-blue-500'
                : 'bg-base text-content-tertiary hover:bg-surface-raised hover:text-content'
            ]"
          >
            {{ ar.label }}
          </button>
        </div>

        <!-- Size Slider -->
        <div class="flex items-center gap-2">
          <input v-no-autocorrect
            v-model.number="megapixels"
            @input="updateFromAspect"
            type="range"
            min="0.5"
            max="4.0"
            step="0.1"
            class="w-32 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
          >
          <span class="text-xs text-content-muted whitespace-nowrap">{{ megapixels.toFixed(1) }}MP</span>
        </div>
      </template>

      <!-- Manual Mode -->
      <template v-else>
        <div class="flex items-center gap-2">
          <input v-no-autocorrect
            v-model.number="localWidth"
            @input="updateFromManual"
            type="number"
            step="64"
            min="256"
            max="2048"
            class="w-20 px-2 py-1 bg-base border border-edge rounded text-content text-xs focus:outline-none focus:border-edge"
          >
          <span class="text-content-muted">×</span>
          <input v-no-autocorrect
            v-model.number="localHeight"
            @input="updateFromManual"
            type="number"
            step="64"
            min="256"
            max="2048"
            class="w-20 px-2 py-1 bg-base border border-edge rounded text-content text-xs focus:outline-none focus:border-edge"
          >
          <button
            @click="swapDimensions"
            class="p-1 bg-surface-raised hover:bg-surface-hover rounded text-content-tertiary text-xs"
            title="Swap"
          >⇄</button>
        </div>
      </template>

      <!-- Auto-change behavior — only when reference images exist -->
      <div v-if="hasReferenceImages" class="border-t border-edge-subtle pt-3 space-y-2">
        <div class="text-[10px] font-medium uppercase tracking-wide text-content-muted">When reference images change</div>
        <div class="grid gap-1">
          <button
            @click="setAutoChangeLock('none')"
            :class="autoLockButtonClass(!lockSize && !lockArea)"
          >Use image size</button>
          <button
            @click="setAutoChangeLock('area')"
            :class="autoLockButtonClass(lockArea)"
          >Maintain {{ megapixelAreaLabel }} area</button>
          <button
            @click="setAutoChangeLock('size')"
            :class="autoLockButtonClass(lockSize)"
          >Maintain current size</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

interface Props {
  width: number
  height: number
  mode?: 'aspect' | 'manual'
  lockSize?: boolean
  lockArea?: boolean
  disabled?: boolean
  compact?: boolean
  // The "when reference images change" behavior is only meaningful when this
  // tool/flow actually takes reference images; hide it otherwise.
  hasReferenceImages?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  compact: false,
  hasReferenceImages: true,
})

const emit = defineEmits<{
  (e: 'update', width: number, height: number): void
  (e: 'update:mode', mode: 'aspect' | 'manual'): void
  (e: 'update:lockSize', value: boolean): void
  (e: 'update:lockArea', value: boolean): void
}>()

const showDropdown = ref(false)
const buttonRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref({})
const mode = ref<'aspect' | 'manual'>(props.mode ?? 'aspect')
watch(() => props.mode, (m) => { if (m && m !== mode.value) mode.value = m })
watch(mode, (m) => { if (m !== props.mode) emit('update:mode', m) })
const selectedAspectRatio = ref('3:4')
const megapixels = ref(1.0)
const localWidth = ref(props.width)
const localHeight = ref(props.height)

const aspectRatios = [
  { label: '9:16', width: 9, height: 16 },
  { label: '3:4', width: 3, height: 4 },
  { label: '1:1', width: 1, height: 1 },
  { label: '4:3', width: 4, height: 3 },
  { label: '16:9', width: 16, height: 9 },
]

// Compute display values
const resolutionSummary = computed(() => {
  return `${props.width}×${props.height}`
})

const megapixelAreaLabel = computed(() => {
  const mp = (props.width * props.height) / 1_000_000
  if (!Number.isFinite(mp) || mp <= 0) return 'current'
  return `${mp < 1 ? mp.toFixed(2) : mp.toFixed(1)}MP`
})

// Aspect ratio preview rectangle style
const aspectPreviewStyle = computed(() => {
  const w = props.width
  const h = props.height
  const maxSize = 12 // max dimension in pixels

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

// Initialize from props
watch(() => [props.width, props.height], ([w, h]) => {
  localWidth.value = w
  localHeight.value = h

  // Detect aspect ratio from current dimensions
  const ratio = w / h
  const matchingAr = aspectRatios.find(ar => {
    const arRatio = ar.width / ar.height
    return Math.abs(arRatio - ratio) < 0.05
  })

  if (matchingAr) {
    selectedAspectRatio.value = matchingAr.label
  }

  // Calculate megapixels
  megapixels.value = Number(((w * h) / 1000000).toFixed(1))
}, { immediate: true })

function toggleDropdown() {
  if (props.disabled) return

  if (!showDropdown.value && buttonRef.value) {
    const rect = buttonRef.value.getBoundingClientRect()
    const dropdownWidth = 220 // Approximate dropdown width
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

function selectAspectRatio(label: string) {
  selectedAspectRatio.value = label
  updateFromAspect()
}

function updateFromAspect() {
  const ar = aspectRatios.find(a => a.label === selectedAspectRatio.value)
  if (!ar) return

  const totalPixels = megapixels.value * 1000000
  const aspectValue = ar.width / ar.height
  const width = Math.sqrt(totalPixels * aspectValue)
  const height = Math.sqrt(totalPixels / aspectValue)

  // Round to nearest multiple of 64
  const roundedWidth = Math.round(width / 64) * 64
  const roundedHeight = Math.round(height / 64) * 64

  localWidth.value = roundedWidth
  localHeight.value = roundedHeight

  emit('update', roundedWidth, roundedHeight)
}

function updateFromManual() {
  emit('update', localWidth.value, localHeight.value)
}

function swapDimensions() {
  const temp = localWidth.value
  localWidth.value = localHeight.value
  localHeight.value = temp
  emit('update', localWidth.value, localHeight.value)
}

function toggleLockSize() {
  emit('update:lockSize', !props.lockSize)
}

function toggleLockArea() {
  emit('update:lockArea', !props.lockArea)
}

function setAutoChangeLock(mode: 'none' | 'area' | 'size') {
  emit('update:lockSize', mode === 'size')
  emit('update:lockArea', mode === 'area')
}

function autoLockButtonClass(active: boolean) {
  return [
    'rounded px-2.5 py-1.5 text-left text-xs font-medium transition-colors',
    active
      ? 'bg-blue-500/15 text-blue-500 ring-1 ring-blue-500/30'
      : 'bg-base text-content-secondary hover:bg-surface-raised hover:text-content'
  ]
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
