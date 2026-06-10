<template>
  <div class="h-full flex flex-col bg-slideshow-matt">
    <LineageTree
      ref="lineageTreeRef"
      :media-id="numericMediaId"
      class="flex-1 min-h-0"
      @focus-changed="onFocusChanged"
    />
  </div>
</template>

<script setup>
import { computed, ref, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import LineageTree from '../components/LineageTree.vue'
import { useWorkspaceTabs } from '../composables/useWorkspaceTabs'
import { useTelemetry } from '../composables/useTelemetry'

const { track } = useTelemetry()
track('lineage_viewed', {}, 'feature')

const props = defineProps({
  mediaId: {
    type: [String, Number],
    required: true
  }
})

const numericMediaId = computed(() => Number(props.mediaId))
const lineageTreeRef = ref(null)
const router = useRouter()
const { updateLineageFocus } = useWorkspaceTabs()

function onFocusChanged(focusedMediaId) {
  updateLineageFocus(String(props.mediaId), String(focusedMediaId))
}

const dirMap = {
  ArrowRight: 'right', ArrowLeft: 'left', ArrowDown: 'down', ArrowUp: 'up',
  d: 'right', a: 'left', s: 'down', w: 'up'
}

function handleKeydown(e) {
  const dir = dirMap[e.key]
  if (dir) {
    e.preventDefault()
    e.stopPropagation()
    lineageTreeRef.value?.navigateDpad?.(dir)
    return
  }

  if (e.key === 'Enter') {
    e.preventDefault()
    e.stopPropagation()
    if (lineageTreeRef.value?.hasDetailOpen?.()) {
      lineageTreeRef.value.closeDetail()
    } else {
      lineageTreeRef.value?.openDetail?.()
    }
    return
  }

  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    if (lineageTreeRef.value?.hasDetailOpen?.()) {
      lineageTreeRef.value.closeDetail()
      return
    }
    router.back()
  }
}

onActivated(() => {
  window.addEventListener('keydown', handleKeydown, true)
})

onDeactivated(() => {
  window.removeEventListener('keydown', handleKeydown, true)
})
</script>
