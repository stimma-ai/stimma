<template>
  <div ref="space" class="relative h-full w-full overflow-hidden">
    <div
      ref="content"
      class="absolute left-1/2 top-1/2 w-full origin-center"
      :style="{ transform: `translate(-50%, -50%) scale(${scale})` }"
    >
      <slot />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const space = ref(null)
const content = ref(null)
const scale = ref(1)

// Measure the untransformed content, so scaling cannot feed back into sizing.
// Observe both boxes: window resizing, wrapped text and errors all affect fit.
watch([space, content], ([container, panel], _, onCleanup) => {
  if (!container || !panel) return
  const fit = () => {
    scale.value = Math.min(1,
      container.clientWidth / Math.max(1, panel.scrollWidth),
      container.clientHeight / Math.max(1, panel.offsetHeight))
  }
  const observer = new ResizeObserver(fit)
  observer.observe(container)
  observer.observe(panel)
  fit()
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })
</script>
