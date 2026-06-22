<template>
  <div v-if="markers.length > 0" class="flex items-center gap-1">
    <button
      v-for="marker in markers"
      :key="marker.id"
      @click="toggleMarker(marker.id)"
      :class="[
        'w-10 h-10 rounded-lg cursor-pointer transition-all border flex items-center justify-center',
        isSelected(marker.id)
          ? 'bg-opacity-30 border-opacity-100'
          : 'bg-overlay-subtle border-edge-subtle text-content-tertiary hover:bg-overlay-light hover:text-content'
      ]"
      :style="isSelected(marker.id) ? { backgroundColor: marker.color + '33', borderColor: marker.color, color: marker.color } : {}"
      :title="marker.name"
    >
      <span v-html="sanitizeSvg(marker.icon_svg)" class="w-4 h-4 flex-shrink-0 icon-container"></span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { sanitizeSvg } from '../../utils/sanitizeHtml'

interface Marker {
  id: number
  name: string
  icon_svg: string
  color: string
}

interface Props {
  markers: Marker[]
  modelValue: number[]  // Selected marker IDs
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: number[]): void
}>()

function isSelected(markerId: number): boolean {
  return props.modelValue.includes(markerId)
}

function toggleMarker(markerId: number) {
  if (isSelected(markerId)) {
    emit('update:modelValue', props.modelValue.filter(id => id !== markerId))
  } else {
    emit('update:modelValue', [...props.modelValue, markerId])
  }
}
</script>
