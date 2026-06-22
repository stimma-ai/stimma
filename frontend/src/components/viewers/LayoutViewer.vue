<template>
  <div
    ref="containerRef"
    class="w-full h-full flex items-center justify-center overflow-hidden"
  >
    <div v-if="loading" class="text-content-tertiary">
      Loading layout...
    </div>

    <div v-else-if="error" class="text-red-500">
      {{ error }}
    </div>

    <div v-else :style="wrapperStyle">
      <iframe
        ref="iframeRef"
        :srcdoc="htmlContent"
        sandbox="allow-same-origin"
        :style="iframeStyle"
        class="border-0 origin-top-left"
        scrolling="no"
        @load="onIframeLoad"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { sanitizeLayoutHtmlForSandbox } from '../../utils/layoutHtml'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  }
})

const loading = ref(true)
const error = ref(null)
const htmlContent = ref('')
const layoutWidth = ref(800)
const layoutHeight = ref(600)
const heightResolved = ref(false)
const iframeRef = ref(null)
const containerRef = ref(null)
const containerWidth = ref(0)
const containerHeight = ref(0)

let resizeObserver = null

onMounted(() => {
  resizeObserver = new ResizeObserver(entries => {
    for (const entry of entries) {
      containerWidth.value = entry.contentRect.width
      containerHeight.value = entry.contentRect.height
    }
  })
  if (containerRef.value) {
    resizeObserver.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})

function onIframeLoad() {
  // For legacy layouts with height="auto", measure from iframe DOM
  if (!heightResolved.value) {
    try {
      const doc = iframeRef.value?.contentDocument
      if (doc) {
        doc.documentElement.style.overflow = 'hidden'
        doc.body.style.overflow = 'hidden'
        const actualHeight = doc.documentElement.scrollHeight
        if (actualHeight > 0) {
          layoutHeight.value = actualHeight
          heightResolved.value = true
        }
      }
    } catch (e) {
      // Cross-origin fallback — keep estimated height
    }
  }
}

const scale = computed(() => {
  if (!containerWidth.value || !containerHeight.value || !layoutWidth.value || !layoutHeight.value) return 1
  const scaleX = containerWidth.value / layoutWidth.value
  const scaleY = containerHeight.value / layoutHeight.value
  return Math.min(scaleX, scaleY, 1)
})

const wrapperStyle = computed(() => ({
  width: `${layoutWidth.value * scale.value}px`,
  height: `${layoutHeight.value * scale.value}px`,
  overflow: 'hidden',
}))

const iframeStyle = computed(() => ({
  width: `${layoutWidth.value}px`,
  height: `${layoutHeight.value}px`,
  transform: `scale(${scale.value})`,
}))

async function loadLayout() {
  loading.value = true
  error.value = null

  try {
    const response = await axios.get(`${getApiBase()}/media/${props.mediaId}/layout-html`)
    htmlContent.value = sanitizeLayoutHtmlForSandbox(response.data)

    const widthMatch = response.data.match(/data-stimma-width="(\d+)"/)
    const heightMatch = response.data.match(/data-stimma-height="(\d+|auto)"/)

    if (widthMatch) {
      layoutWidth.value = parseInt(widthMatch[1])
    }
    if (heightMatch && heightMatch[1] !== 'auto') {
      layoutHeight.value = parseInt(heightMatch[1])
      heightResolved.value = true
    } else {
      // Legacy layout with auto height — estimate until iframe loads and we measure
      layoutHeight.value = layoutWidth.value * 1.5
      heightResolved.value = false
    }
  } catch (e) {
    error.value = `Failed to load layout: ${e.message}`
  } finally {
    loading.value = false
  }
}

watch(() => props.mediaId, loadLayout, { immediate: true })
</script>
