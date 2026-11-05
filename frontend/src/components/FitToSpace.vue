<template>
  <div ref="space" class="relative h-full w-full overflow-hidden">
    <div
      ref="content"
      class="absolute left-1/2 w-full"
      :class="align === 'top' ? 'top-0 origin-top' : 'top-1/2 origin-center'"
      :style="{ transform: align === 'top' ? `translateX(-50%) scale(${scale})` : `translate(-50%, -50%) scale(${scale})` }"
    >
      <slot />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

// align: 'center' (default) centers the content; 'top' pins it to the top edge.
defineProps({ align: { type: String, default: 'center' } })

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
