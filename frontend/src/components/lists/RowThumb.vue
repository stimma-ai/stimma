<script lang="ts">
// One format read per media id, shared by every row and every list.
const infoCache = new Map<number, Promise<{ format: string } | null>>()
</script>

<script setup lang="ts">
// The leading thumbnail of a list row, a 40px slot. With media it is a square
// on the matte (media law). Without media, or when it will not load, the slot
// holds the row type's glyph (slot) alone: quiet, no box, so a list of rows
// without art does not read as a column of dark tiles.
//
// What is drawn depends on what the media is, which the list payload does not
// say, so the format is read once per media id (cached across rows):
//   - a set shows its cover, the top card of the stacked preview, cropped to
//     fill the slot; at 40px the fan of cards behind it is only noise.
//   - a vector (SVG) draws the document itself on the transparency checker.
//     Its raster thumbnail comes from a desktop renderer that a browser tab or
//     a headless server does not have, and the document needs no renderer.
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

interface Info { format: string }
function loadInfo(id: number): Promise<Info | null> {
  let pending = infoCache.get(id)
  if (!pending) {
    pending = getMediaItem(id)
      .then((item: any) => ({ format: String(item?.file_format || '').toLowerCase() }))
      .catch(() => null)
    infoCache.set(id, pending)
  }
  return pending
}

const failed = ref(false)
const loaded = ref(false)
const info = ref<Info | null>(null)
const infoReady = ref(false)

watch(() => [props.mediaId, props.fileHash], () => { failed.value = false; loaded.value = false })
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

const kind = computed<'set' | 'vector' | 'plain'>(() => {
  const format = info.value?.format ?? ''
  if (format === 'svg') return 'vector'
  if (format.startsWith('stimmaset')) return 'set'
  return 'plain'
})
const showImage = computed(() => props.mediaId != null && infoReady.value && !failed.value)
</script>

<template>
  <div
    class="relative flex h-10 w-10 flex-shrink-0 items-center justify-center"
    :class="showImage && loaded ? 'overflow-hidden rounded-media bg-matte' : 'text-content-muted'"
  >
    <span v-if="!showImage || !loaded" class="flex h-5 w-5 items-center justify-center opacity-50" aria-hidden="true">
      <slot />
    </span>
    <div v-if="showImage" class="absolute inset-0 overflow-hidden rounded-media" :class="loaded ? '' : 'opacity-0'">
      <!-- Vector: the document, contained, on the transparency checker. -->
      <div v-if="kind === 'vector'" class="absolute inset-1">
        <MediaImage
          :media-id="mediaId!"
          :file-hash="fileHash"
          :thumbnail="false"
          :contain="true"
          :has-alpha="true"
          :draggable="false"
          :enable-context-menu="false"
          container-class="w-full h-full"
          background-class="bg-transparent"
          @load="loaded = true"
          @error="failed = true"
        />
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
