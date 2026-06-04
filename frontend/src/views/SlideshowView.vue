<template>
  <SlideshowMode
    :total-count="totalCount"
    :start-index="startIndex"
    :page-provider="pageProvider"
    :randomized="randomized"
    :random-seed="randomSeed"
    :inline="true"
    @close="handleClose"
    @update:index="onIndexChange"
  />
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import SlideshowMode from '../components/SlideshowMode.vue'
import { useTabNavigation } from '../composables/useTabNavigation'
import { useTelemetry } from '../composables/useTelemetry'

const { track } = useTelemetry()
track('slideshow_enter')

// Define component name for keep-alive exclude pattern
defineOptions({
  name: 'SlideshowView'
})

const props = defineProps({
  totalCount: {
    type: Number,
    required: true
  },
  startIndex: {
    type: Number,
    default: 0
  },
  pageProvider: {
    type: Function,
    required: true
  },
  randomized: {
    type: Boolean,
    default: false
  },
  randomSeed: {
    type: Number,
    default: null
  }
})

const { goBack } = useTabNavigation()

// Track unique media items seen
const seenIndices = ref(new Set([props.startIndex]))

function onIndexChange(index) {
  seenIndices.value.add(index)
}

onUnmounted(() => {
  track('slideshow_leave', { itemsSeen: seenIndices.value.size })
})

// Handle close by going back in stack
function handleClose() {
  goBack()
}
</script>
