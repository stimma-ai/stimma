<script lang="ts">
// One format read per media id, shared by every row and every list.
const infoCache = new Map<number, Promise<{ format: string; hasAlpha: boolean } | null>>()
</script>

<script setup lang="ts">
// The leading thumbnail of a list row, a 40px slot. With media it is a square
// on the matte (media law). Without media, or when it will not load, the slot
// is a real square of the same size on the raised surface holding the row
// type's glyph (slot), so the thumbnail column has no holes.
//
// What is drawn depends on what the media is, which the list payload does not
// say, so the format is read once per media id (cached across rows):
//   - a set shows its cover, the top card of the stacked preview, cropped to
//     fill the slot; at 40px the fan of cards behind it is only noise.
//   - transparent artwork (a vector, or a file with an alpha channel) is drawn
//     whole on the transparency checker, never cropped. A vector draws the
//     document itself: its raster thumbnail comes from a desktop renderer that
//     a browser tab or a headless server does not have, and the document needs
//     no renderer. Such art usually carries empty margin, so it would read as a
//     tiny mark beside a photo that fills the slot. Once it loads, the opaque
//     bounds are measured on a small canvas and the art is enlarged to fill
//     the slot, by at most 1.6x and never past the slot's edge. If the pixels
//     cannot be read, a fixed 1.25x stands in.
//   - everything else uses the thumbnail, and falls back to the glyph if it
//     cannot be had (a layout bundle with no renderer attached).
import { computed, ref, watch } from 'vue'
import { MediaImage } from '../media'
import { useMediaApi } from '../../composables/useMediaApi'

const props = defineProps<{
  mediaId?: number | null
  fileHash?: string
  thumbnailSize?: number
}>()

const { getMediaItem } = useMediaApi()

interface Info { format: string; hasAlpha: boolean }
function loadInfo(id: number): Promise<Info | null> {
  let pending = infoCache.get(id)
  if (!pending) {
    pending = getMediaItem(id)
      .then((item: any) => ({
        format: String(item?.file_format || '').toLowerCase(),
        hasAlpha: item?.has_alpha === true,
      }))
      .catch(() => null)
    infoCache.set(id, pending)
  }
  return pending
}

const failed = ref(false)
const loaded = ref(false)
const info = ref<Info | null>(null)
const infoReady = ref(false)

const fit = ref({ scale: 1, x: 0, y: 0 })

watch(() => [props.mediaId, props.fileHash], () => {
  failed.value = false
  loaded.value = false
  fit.value = { scale: 1, x: 0, y: 0 }
})
watch(
  () => props.mediaId,
  async (id) => {
    info.value = null
    infoReady.value = false
    if (id == null) return
    const loaded = await loadInfo(id)
    if (id !== props.mediaId) return
    info.value = loaded
    infoReady.value = true
  },
  { immediate: true },
)

const kind = computed<'set' | 'vector' | 'transparent' | 'plain'>(() => {
  const format = info.value?.format ?? ''
  if (format === 'svg') return 'vector'
  if (format.startsWith('stimmaset')) return 'set'
  if (info.value?.hasAlpha) return 'transparent'
  return 'plain'
})
const isTransparent = computed(() => kind.value === 'vector' || kind.value === 'transparent')

// Optical sizing for transparent art: scale and centre its opaque bounds in
// the slot. The slot itself never changes size.
const MAX_FIT = 1.6
const FALLBACK_FIT = 1.25
const FILL = 0.92
function measureFit(event: Event) {
  const img = event.target as HTMLImageElement | null
  const fallback = { scale: FALLBACK_FIT, x: 0, y: 0 }
  if (!img || !img.naturalWidth || !img.naturalHeight) { fit.value = fallback; return }
  try {
    const size = 48
    const ratio = img.naturalWidth / img.naturalHeight
    const w = ratio >= 1 ? size : Math.max(1, Math.round(size * ratio))
    const h = ratio >= 1 ? Math.max(1, Math.round(size / ratio)) : size
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) { fit.value = fallback; return }
    const ox = Math.floor((size - w) / 2)
    const oy = Math.floor((size - h) / 2)
    ctx.drawImage(img, ox, oy, w, h)
    const data = ctx.getImageData(0, 0, size, size).data
    let minX = size, minY = size, maxX = -1, maxY = -1
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        if (data[(y * size + x) * 4 + 3] > 24) {
          if (x < minX) minX = x
          if (x > maxX) maxX = x
          if (y < minY) minY = y
          if (y > maxY) maxY = y
        }
      }
    }
    if (maxX < 0) { fit.value = { scale: 1, x: 0, y: 0 }; return }
    const cw = (maxX - minX + 1) / size
    const ch = (maxY - minY + 1) / size
    const scale = Math.min(MAX_FIT, Math.max(1, FILL / Math.max(cw, ch)))
    const cx = (minX + maxX + 1) / 2 / size
    const cy = (minY + maxY + 1) / 2 / size
    fit.value = { scale, x: -(cx - 0.5) * scale, y: -(cy - 0.5) * scale }
  } catch {
    fit.value = fallback
  }
}
function onTransparentLoad(event: Event) {
  measureFit(event)
  loaded.value = true
}
const fitStyle = computed(() => ({
  transform: `translate(${(fit.value.x * 100).toFixed(2)}%, ${(fit.value.y * 100).toFixed(2)}%) scale(${fit.value.scale.toFixed(3)})`,
}))
const showImage = computed(() => props.mediaId != null && infoReady.value && !failed.value)
</script>

<template>
  <div
    class="relative flex h-10 w-10 flex-shrink-0 items-center justify-center"
    :class="showImage && loaded ? 'overflow-hidden rounded-media bg-matte' : 'rounded-media bg-surface-raised text-content-tertiary'"
  >
    <span v-if="!showImage || !loaded" class="flex h-5 w-5 items-center justify-center" aria-hidden="true">
      <slot />
    </span>
    <div v-if="showImage" class="absolute inset-0 overflow-hidden rounded-media" :class="loaded ? '' : 'opacity-0'">
      <!-- Transparent art: whole, on the checker, enlarged to its opaque
           bounds. The checker stays on the unscaled slot. -->
      <div v-if="isTransparent" class="absolute inset-0 bg-checker">
        <div class="absolute inset-0" :style="fitStyle">
          <MediaImage
            :media-id="mediaId!"
            :file-hash="fileHash"
            :thumbnail="kind !== 'vector'"
            :thumbnail-size="192"
            thumbnail-mode="fit"
            :contain="true"
            :draggable="false"
            :enable-context-menu="false"
            container-class="w-full h-full"
            background-class="bg-transparent"
            @load="onTransparentLoad"
            @error="failed = true"
          />
        </div>
      </div>
      <!-- Set: the top card of the stacked preview fills the slot. -->
      <div
        v-else-if="kind === 'set'"
        class="absolute h-[155%] w-[155%] left-[-40.7%] top-[-40.7%]"
      >
        <MediaImage
          :media-id="mediaId!"
          :file-hash="fileHash"
          :thumbnail="true"
          :thumbnail-size="192"
          :draggable="false"
          :enable-context-menu="false"
          container-class="w-full h-full"
          background-class="bg-transparent"
          img-class="w-full h-full object-cover"
          @load="loaded = true"
          @error="failed = true"
        />
      </div>
      <div v-else class="absolute inset-0">
        <MediaImage
          :media-id="mediaId!"
          :file-hash="fileHash"
          :thumbnail="true"
          :thumbnail-size="thumbnailSize || 80"
          :draggable="false"
          :enable-context-menu="false"
          container-class="w-full h-full"
          background-class="bg-transparent"
          img-class="w-full h-full object-cover"
          @load="loaded = true"
          @error="failed = true"
        />
      </div>
    </div>
  </div>
</template>
