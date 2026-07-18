<template>
  <div class="relative">
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      class="flex items-center gap-2 px-2.5 py-2 rounded-md text-content-secondary text-sm hover:bg-overlay-subtle hover:text-content transition-colors duration-150 whitespace-nowrap"
    >
      <!-- Aspect ratio preview rectangle -->
      <span
        class="border border-edge-subtle bg-surface-raised flex-shrink-0"
        :style="aspectPreviewStyle"
      ></span>
      <span>{{ displayText }}</span>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <div
      v-if="showDropdown"
      class="fixed bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu p-3 space-y-2"
      :style="dropdownStyle"
      @click.stop
    >
      <div class="flex gap-1 flex-wrap">
        <button
          v-for="group in groupedDimensions"
          :key="group.label"
          @click="selectGroup(group)"
          :class="[
            'px-2 py-1 rounded-md text-xs font-medium transition-colors duration-150',
            isGroupSelected(group)
              ? 'bg-accent text-white'
              : 'bg-overlay-subtle text-content-tertiary hover:bg-overlay-light'
          ]"
        >
          {{ group.label }}
        </button>
      </div>
      <!-- Show selected dimensions -->
      <div v-if="selectedGroup && selectedGroup.pairs.length > 1" class="flex gap-1 flex-wrap pt-1 border-t border-edge-subtle">
        <button
          v-for="pair in selectedGroup.pairs"
          :key="`${pair[0]}x${pair[1]}`"
          @click="selectPair(pair)"
          :class="[
            'px-2 py-1 rounded-md text-xs font-medium font-mono tabular-nums transition-colors duration-150',
            width === pair[0] && height === pair[1]
              ? 'bg-accent/60 text-white'
              : 'bg-overlay-subtle text-content-tertiary hover:bg-overlay-light'
          ]"
        >
          {{ pair[0] }}&times;{{ pair[1] }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface Props {
  allowedDimensions: [number, number][]
  width: number
  height: number
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update', width: number, height: number): void
}>()

const showDropdown = ref(false)
const buttonRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref({})

interface DimensionGroup {
  label: string
  ratio: number
  pairs: [number, number][]
}

function deriveAspectLabel(w: number, h: number): string {
  const g = gcd(w, h)
  const rw = w / g
  const rh = h / g
  // If the simplified ratio has small numbers, use it directly
  if (rw <= 21 && rh <= 21) {
    return `${rw}:${rh}`
  }
  // Otherwise approximate to common ratios
  const ratio = w / h
  const common: [number, string][] = [
    [1, '1:1'],
    [4/5, '4:5'],
    [3/4, '3:4'],
    [2/3, '2:3'],
    [9/16, '9:16'],
    [5/4, '5:4'],
    [4/3, '4:3'],
    [3/2, '3:2'],
    [16/9, '16:9'],
    [21/9, '21:9'],
  ]
  let bestLabel = `${rw}:${rh}`
  let bestDiff = Infinity
  for (const [r, label] of common) {
    const diff = Math.abs(ratio - r)
    if (diff < bestDiff) {
      bestDiff = diff
      bestLabel = diff < 0.05 ? label : `~${label}`
    }
  }
  return bestLabel
}

function gcd(a: number, b: number): number {
  while (b) {
    ;[a, b] = [b, a % b]
  }
  return a
}

const groupedDimensions = computed((): DimensionGroup[] => {
  const groups = new Map<string, DimensionGroup>()
  for (const pair of props.allowedDimensions) {
    const [w, h] = pair
    const label = deriveAspectLabel(w, h)
    const ratio = w / h
    if (!groups.has(label)) {
      groups.set(label, { label, ratio, pairs: [] })
    }
    groups.get(label)!.pairs.push(pair)
  }
  // Sort: portrait (ratio < 1) ascending, then square, then landscape descending
  return Array.from(groups.values()).sort((a, b) => a.ratio - b.ratio)
})

const selectedGroup = computed((): DimensionGroup | null => {
  for (const group of groupedDimensions.value) {
    for (const pair of group.pairs) {
      if (pair[0] === props.width && pair[1] === props.height) {
        return group
      }
    }
  }
  return null
})

function isGroupSelected(group: DimensionGroup): boolean {
  return group.pairs.some(p => p[0] === props.width && p[1] === props.height)
}

const displayText = computed(() => {
  const group = selectedGroup.value
  if (group) {
    if (group.pairs.length > 1) {
      return `${group.label} · ${props.width}×${props.height}`
    }
    return group.label
  }
  return `${props.width}×${props.height}`
})

const aspectPreviewStyle = computed(() => {
  const w = props.width
  const h = props.height
  const maxSize = 16
  if (w >= h) {
    return { width: `${maxSize}px`, height: `${Math.round((h / w) * maxSize)}px` }
  } else {
    return { width: `${Math.round((w / h) * maxSize)}px`, height: `${maxSize}px` }
  }
})

function toggleDropdown() {
  if (!showDropdown.value && buttonRef.value) {
    const rect = buttonRef.value.getBoundingClientRect()
    const dropdownWidth = 300
    const viewportWidth = window.innerWidth
    const padding = 16
    let left = rect.left
    if (left + dropdownWidth > viewportWidth - padding) {
      left = Math.max(padding, rect.right - dropdownWidth)
    }
    dropdownStyle.value = {
      top: `${rect.bottom + 4}px`,
      left: `${left}px`,
    }
  }
  showDropdown.value = !showDropdown.value
}

function selectGroup(group: DimensionGroup) {
  // If already in this group, don't change
  if (isGroupSelected(group)) return
  // Select the first pair in the group
  const pair = group.pairs[0]
  emit('update', pair[0], pair[1])
}

function selectPair(pair: [number, number]) {
  emit('update', pair[0], pair[1])
}

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
