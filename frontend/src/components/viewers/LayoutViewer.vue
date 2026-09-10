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
        :sandbox="isMobileShell() ? 'allow-same-origin' : undefined"
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
import { isMobileShell } from '../../desktop/mobileBridge'
import { getApiBase } from '../../apiConfig'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['document-touchstart', 'document-touchmove', 'document-touchend', 'document-touchcancel', 'document-click'])
let removeDocumentTouches = () => {}

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
  removeDocumentTouches()
})

function onIframeLoad() {
  // Iframe events do not bubble to the slideshow. Forward the original
  // events so its gesture recognizer can still exclude links and controls.
  removeDocumentTouches()
  try {
    const doc = iframeRef.value?.contentDocument
    if (doc) {
      const handlers = ['touchstart', 'touchmove', 'touchend', 'touchcancel'].map(type => {
        const handler = event => {
          const frame = iframeRef.value
          if (!frame) return
          const rect = frame.getBoundingClientRect()
          const mapTouches = touches => Array.from(touches, touch => ({
            identifier: touch.identifier,
            clientX: rect.left + touch.clientX * rect.width / (frame.clientWidth || 1),
            clientY: rect.top + touch.clientY * rect.height / (frame.clientHeight || 1),
          }))
          emit(`document-${type}`, {
            target: event.target,
            touches: mapTouches(event.touches),
            changedTouches: mapTouches(event.changedTouches),
            cancelable: event.cancelable,
            preventDefault: () => event.preventDefault(),
          })
        }
        doc.addEventListener(type, handler, { capture: true, passive: false })
        return [type, handler]
      })
      const suppressClick = event => emit('document-click', event)
      doc.addEventListener('click', suppressClick, true)
      removeDocumentTouches = () => {
        for (const [type, handler] of handlers) doc.removeEventListener(type, handler, true)
        doc.removeEventListener('click', suppressClick, true)
      }
    }
  } catch { /* Cross-origin layouts retain their own interaction handling. */ }
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
    htmlContent.value = response.data

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
