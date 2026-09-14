<template>
  <canvas ref="el" class="pointer-events-none h-full w-full" aria-hidden="true" />
</template>

<script setup>
// Dithered glow renderer.
// Soft glows over a dark surface span only ~10 8-bit levels, so ANY smooth CSS
// falloff (gradient or blur) quantizes into visible rings. Drawing the falloff
// into a canvas with noise added BEFORE quantization (true dithering) is the
// only artifact-free way to render them.
//
// blobs: [{ x, y, rx, ry, color: [r,g,b], alpha }] in unit coordinates of the
// canvas box. Re-renders when the box resizes or the blobs change.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  blobs: { type: Array, required: true },
})

const el = ref(null)
let observer = null
let raf = 0

function render() {
  const canvas = el.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const scale = Math.min(window.devicePixelRatio || 1, 1.5)
  const w = Math.max(1, Math.round(rect.width * scale))
  const hgt = Math.max(1, Math.round(rect.height * scale))
  canvas.width = w
  canvas.height = hgt
  const ctx = canvas.getContext('2d')
  const img = ctx.createImageData(w, hgt)
  const data = img.data
  const blobs = props.blobs.map(b => ({
    cx: b.x * w, cy: b.y * hgt, rx: b.rx * w, ry: b.ry * hgt,
    r: b.color[0], g: b.color[1], b: b.color[2], a: b.alpha,
  }))
  let i = 0
  for (let y = 0; y < hgt; y++) {
    for (let x = 0; x < w; x++) {
      let r = 0, g = 0, bl = 0, a = 0
      for (const blob of blobs) {
        const dx = (x - blob.cx) / blob.rx
        const dy = (y - blob.cy) / blob.ry
        const wgt = Math.exp(-(dx * dx + dy * dy) * 2.2) * blob.a
        r += blob.r * wgt; g += blob.g * wgt; bl += blob.b * wgt; a += wgt
      }
      if (a > 0.001) {
        const n = (Math.random() - 0.5) * 2
        data[i] = Math.max(0, Math.min(255, r / a + n))
        data[i + 1] = Math.max(0, Math.min(255, g / a + n))
        data[i + 2] = Math.max(0, Math.min(255, bl / a + n))
        data[i + 3] = Math.max(0, Math.min(255, a * 255 + (Math.random() - 0.5) * 2.5))
      }
      i += 4
    }
  }
  ctx.putImageData(img, 0, 0)
}

function scheduleRender() {
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(render)
}

onMounted(() => {
  render()
  observer = new ResizeObserver(scheduleRender)
  observer.observe(el.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(raf)
})
watch(() => props.blobs, scheduleRender)
</script>
