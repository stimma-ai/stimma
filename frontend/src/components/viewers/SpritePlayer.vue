<!--
  Viewer for .stimmasprite.json documents: canvas playback of one animation at
  a time, driven by the document (fps, per-frame durations, loop mode) rather
  than the WebP's embedded timing.

  Frames decode through the ImageDecoder API (Chromium/Electron) so the
  scrubber can step and hold individual frames. Without ImageDecoder the
  animated WebP plays inside an <img> and the transport hides frame control.

  Chrome follows the approved SpritePlayer mock: matte behind the stage,
  transport with play/loop going `live` when armed, per-frame ticks with the
  loop span tinted, a readout that toggles time ⇄ frames (persisted with the
  frame-mode key convention), and animation chips where indigo = selected.
  Clicks on the artwork bubble so the host can open the slideshow or a context
  menu; the control rows stop them.
-->
<template>
  <div
    ref="containerRef"
    :class="[
      'w-full h-full flex flex-col overflow-hidden',
      overlay ? 'relative items-center justify-center bg-slideshow-matt' : 'items-stretch',
    ]"
  >
    <div v-if="loading" class="flex-1 flex items-center justify-center text-content-tertiary text-sm">
      Loading…
    </div>

    <div v-else-if="error" class="flex-1 flex items-center justify-center text-sm text-content-secondary px-6 text-center">
      {{ error }}
    </div>

    <template v-else>
      <!-- Stage -->
      <div
        ref="stageRef"
        :class="[
          'flex items-center justify-center overflow-hidden',
          overlay ? 'absolute inset-0' : 'relative flex-1 min-h-0 w-full bg-slideshow-matt rounded-media',
        ]"
      >
        <canvas
          v-if="decoded"
          ref="canvasRef"
          :width="frameWidth"
          :height="frameHeight"
          :style="canvasStyle"
          class="block"
          :aria-label="`Sprite animation ${current?.name ?? ''}`"
        />
        <img
          v-else-if="current?.url"
          :src="current.url"
          :style="canvasStyle"
          class="block"
          alt="Sprite animation"
          draggable="false"
        />
        <div
          v-if="overlay && current"
          class="absolute top-3.5 left-4 text-[11px] text-content-secondary pointer-events-none"
        >
          {{ animationLabel(current) }}
        </div>
      </div>

      <!-- Transport -->
      <div
        v-if="current"
        :class="[
          'flex items-center gap-2.5 cursor-default',
          overlay
            ? 'absolute left-1/2 bottom-[18px] -translate-x-1/2 w-[min(520px,90%)] px-3 py-1.5 rounded-lg bg-black/85 border border-edge-subtle backdrop-blur'
            : 'flex-shrink-0 px-1 pt-2',
        ]"
        @click.stop
        @contextmenu.stop
        @pointerdown.stop
        @wheel.stop
        @dblclick.stop
      >
        <button
          type="button"
          :class="['sprite-tbtn', { '!text-live hover:!text-live/80': playing }]"
          :title="playing ? 'Pause (space)' : 'Play (space)'"
          @click="togglePlay"
        >
          <PauseIcon v-if="playing" class="w-3.5 h-3.5" />
          <PlayIcon v-else class="w-3.5 h-3.5" />
        </button>
        <button type="button" class="sprite-tbtn" title="Previous frame" :disabled="!decoded" @click="step(-1)">
          <BackwardIcon class="w-3.5 h-3.5" />
        </button>
        <button type="button" class="sprite-tbtn" title="Next frame" :disabled="!decoded" @click="step(1)">
          <ForwardIcon class="w-3.5 h-3.5" />
        </button>

        <div
          ref="scrubRef"
          class="relative flex-1 h-[26px]"
          :class="decoded ? 'cursor-pointer' : 'opacity-40'"
          @pointerdown="onScrubPointer"
          @pointermove="onScrubPointer"
        >
          <div class="absolute left-0 right-0 top-[11px] h-1 rounded-sm bg-white/10" />
          <div
            class="absolute top-[11px] h-1 rounded-sm bg-live/35"
            :style="{ left: `${loopSpan.left}%`, width: `${loopSpan.width}%` }"
          />
          <div
            v-for="i in tickCount"
            :key="i"
            class="absolute top-[9px] w-px h-2 bg-white/15"
            :style="{ left: `${tickCount > 1 ? ((i - 1) / (tickCount - 1)) * 100 : 0}%` }"
          />
          <div
            class="absolute top-1.5 w-[3px] h-3.5 rounded-[1px] bg-accent -translate-x-px"
            :style="{ left: `${headPercent}%` }"
          />
        </div>

        <button
          type="button"
          :class="['sprite-tbtn', { '!text-live hover:!text-live/80': loop }]"
          title="Toggle loop"
          @click="loop = !loop"
        >
          <ArrowPathIcon class="w-3.5 h-3.5" />
        </button>

        <button
          type="button"
          class="min-w-[52px] text-right text-[11px] tabular-nums text-content-secondary hover:text-content bg-transparent border-none cursor-pointer"
          :title="readoutMode === 'frames' ? 'Show time' : 'Show frames'"
          @click="toggleReadout"
        >
          {{ readout }}
        </button>
      </div>

      <!-- Animation chips -->
      <div
        v-if="names.length > 1 || directions.length > 1"
        :class="[
          'flex-shrink-0 flex flex-wrap items-center gap-1.5 cursor-default',
          overlay
            ? 'absolute left-1/2 bottom-16 -translate-x-1/2 w-[min(520px,90%)] max-h-[35%] overflow-y-auto px-3 py-2 rounded-lg bg-black/85 backdrop-blur'
            : 'px-1 pt-2.5 pb-0.5',
        ]"
        @click.stop
        @contextmenu.stop
        @pointerdown.stop
      >
        <button
          v-for="name in names"
          :key="`name-${name}`"
          type="button"
          :class="[
            'px-2.5 py-[3px] rounded-md text-xs border-none cursor-pointer transition-colors',
            name === selectedName
              ? 'bg-selection/[0.18] text-selection'
              : 'bg-white/5 text-content-secondary hover:text-content',
          ]"
          @click="selectName(name)"
        >
          {{ name }}
        </button>
        <template v-if="directions.length > 1">
          <span class="w-px h-4 bg-edge-subtle mx-1" />
          <button
            v-for="direction in directions"
            :key="`dir-${direction}`"
            type="button"
            :class="[
              'px-2 py-[3px] rounded-md text-[11px] border-none cursor-pointer transition-colors',
              direction === selectedDirection
                ? 'bg-selection/[0.18] text-selection'
                : 'bg-white/5 text-content-secondary hover:text-content',
            ]"
            @click="selectDirection(direction)"
          >
            {{ direction }}
          </button>
        </template>
        <span v-if="current" class="ml-auto self-center text-[11px] text-content-muted tabular-nums">
          {{ current.fps }} fps · {{ current.loop }}
        </span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ArrowPathIcon, BackwardIcon, ForwardIcon, PauseIcon, PlayIcon } from '@heroicons/vue/24/solid'
import { useMediaApi } from '../../composables/useMediaApi'
import { makeProfileKey } from '../../utils/storageKeys'
import { nextSpriteFrame, spriteFrameIndices } from '../../utils/spritePlayback.js'

const props = defineProps({
  mediaId: { type: [Number, String], required: true },
  /** Slideshow chrome: full-bleed stage with a floating transport. */
  overlay: { type: Boolean, default: false },
  /** Start playing as soon as frames are ready. */
  autoplay: { type: Boolean, default: true },
})

const emit = defineEmits(['loaded'])

const { getMediaFileUrl } = useMediaApi()

const FRAME_MODE_KEY = 'sprite-player'

const containerRef = ref(null)
const stageRef = ref(null)
const canvasRef = ref(null)
const scrubRef = ref(null)

const loading = ref(true)
const error = ref(null)
const doc = ref(null)
const animations = ref([]) // [{ key, name, direction, fps, loop, loopStart, loopEnd, frameCount, durations, url, style }]
const selectedName = ref(null)
const selectedDirection = ref(null)

const decoded = ref(false)
const frames = ref([]) // ImageBitmap[] for the current animation
const frameIndex = ref(0)
const playing = ref(false)
const loop = ref(true)
const readoutMode = ref('frames')
const stageSize = ref({ width: 0, height: 0 })
const pixelated = ref(false)

let playbackDirection = 1
let timer = null
let decodeToken = 0
let resizeObserver = null

// --- document -------------------------------------------------------------

function animationLabel(anim) {
  return anim.direction ? `${anim.name} · ${anim.direction}` : anim.name
}

const names = computed(() => [...new Set(animations.value.map(a => a.name))])
const directions = computed(() =>
  animations.value.filter(a => a.name === selectedName.value && a.direction).map(a => a.direction)
)
const current = computed(() =>
  animations.value.find(a => a.name === selectedName.value && (a.direction ?? null) === (selectedDirection.value ?? null))
  ?? animations.value.find(a => a.name === selectedName.value)
  ?? null
)

const frameWidth = computed(() => frames.value[0]?.width || 1)
const frameHeight = computed(() => frames.value[0]?.height || 1)

const canvasStyle = computed(() => {
  const { width: sw, height: sh } = stageSize.value
  const fw = frameWidth.value
  const fh = frameHeight.value
  if (!sw || !sh) return {}
  const margin = props.overlay ? 0.8 : 0.9
  let scale = Math.min((sw * margin) / fw, (sh * margin) / fh)
  // Pixel styles read best at integer multiples; never below 1× if it fits.
  if (pixelated.value && scale >= 1) scale = Math.floor(scale)
  if (scale <= 0) scale = 1
  return {
    width: `${Math.round(fw * scale)}px`,
    height: `${Math.round(fh * scale)}px`,
    imageRendering: pixelated.value ? 'pixelated' : 'auto',
  }
})

async function loadContent() {
  loading.value = true
  error.value = null
  stopPlayback()
  try {
    const { data } = await axios.get(`/api/media/${props.mediaId}/content`)
    doc.value = data
    const style = String(data.style || '').toLowerCase()
    const preset = String(data.production?.style?.preset || '').toLowerCase()
    pixelated.value = ['pixel', '8-bit', '16-bit', '1-bit', 'retro'].some(t => style.includes(t) || preset.includes(t))
    animations.value = (data.animations || [])
      .filter(a => a && a.animation)
      .map(a => {
        const resolved = a.animation.resolved
        const fps = Number(a.fps) || 12
        const base = Math.max(1, Math.round(1000 / fps))
        const durations = (a.frames || []).map(f => (f && f.duration_ms ? Number(f.duration_ms) : base))
        return {
          key: a.direction ? `${a.name}_${a.direction}` : a.name,
          name: a.name,
          direction: a.direction || null,
          fps,
          loop: a.loop || 'loop',
          loopStart: Number(a.loop_start) || 0,
          loopEnd: a.loop_end != null ? Number(a.loop_end) : Math.max(0, (a.frame_count || durations.length) - 1),
          frameCount: a.frame_count || durations.length,
          frameIndices: a.animation.frame_indices,
          durations,
          url: resolved ? getMediaFileUrl(resolved.file_hash || resolved.media_id) : null,
        }
      })
    // Idle first, as the document's natural resting move.
    const idle = animations.value.find(a => a.name.toLowerCase() === 'idle')
    const first = idle || animations.value[0]
    selectedName.value = first?.name ?? null
    selectedDirection.value = first?.direction ?? null
    emit('loaded', { title: data.title, animations: animations.value.length })
    if (!first) error.value = 'This sprite has no animations yet.'
  } catch (e) {
    console.error('[SpritePlayer] failed to load sprite content', e)
    error.value = 'Failed to load sprite'
  } finally {
    loading.value = false
  }
}

function selectName(name) {
  selectedName.value = name
  const withDir = animations.value.find(a => a.name === name && a.direction === selectedDirection.value)
  if (!withDir) selectedDirection.value = animations.value.find(a => a.name === name)?.direction ?? null
}

function selectDirection(direction) {
  selectedDirection.value = direction
}

// --- decoding -------------------------------------------------------------

function releaseFrames() {
  for (const bitmap of new Set(frames.value)) {
    try { bitmap.close?.() } catch { /* ignore */ }
  }
  frames.value = []
}

async function decodeCurrent() {
  const anim = current.value
  const token = ++decodeToken
  stopPlayback()
  releaseFrames()
  decoded.value = false
  frameIndex.value = 0
  playbackDirection = 1
  loop.value = anim?.loop !== 'once'
  if (!anim?.url) return
  if (typeof window === 'undefined' || typeof window.ImageDecoder !== 'function') {
    // Fallback: the <img> plays the animated WebP natively; no frame control.
    if (props.autoplay) playing.value = true
    return
  }
  try {
    const response = await fetch(anim.url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const buffer = await response.arrayBuffer()
    if (token !== decodeToken) return
    const decoder = new window.ImageDecoder({ data: buffer, type: 'image/webp' })
    await decoder.tracks.ready
    const track = decoder.tracks.selectedTrack
    const count = track ? track.frameCount : 0
    const bitmaps = []
    const encodedDurations = []
    for (let i = 0; i < count; i++) {
      const { image } = await decoder.decode({ frameIndex: i })
      const bitmap = await createImageBitmap(image)
      encodedDurations.push(Math.round((image.duration || 0) / 1000))
      image.close?.()
      bitmaps.push(bitmap)
      if (token !== decodeToken) {
        bitmaps.forEach(b => b.close?.())
        decoder.close?.()
        return
      }
    }
    decoder.close?.()
    let mapping
    try {
      mapping = spriteFrameIndices(anim, encodedDurations)
    } catch (e) {
      bitmaps.forEach(b => b.close?.())
      error.value = e.message
      return
    }
    frames.value = mapping.map(i => bitmaps[i])
    const used = new Set(mapping)
    bitmaps.forEach((b, i) => { if (!used.has(i)) b.close?.() })
    decoded.value = bitmaps.length > 0
    await nextTick()
    measureStage()
    draw()
    if (props.autoplay && decoded.value) start()
  } catch (e) {
    console.warn('[SpritePlayer] ImageDecoder failed, falling back to <img>', e)
    decoded.value = false
    if (props.autoplay) playing.value = true
  }
}

// --- playback -------------------------------------------------------------

function draw() {
  const canvas = canvasRef.value
  const bitmap = frames.value[frameIndex.value]
  if (!canvas || !bitmap) return
  const ctx = canvas.getContext('2d')
  ctx.imageSmoothingEnabled = !pixelated.value
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(bitmap, 0, 0)
}

function scheduleNext() {
  const anim = current.value
  if (!anim || !decoded.value) return
  const ms = anim.durations[frameIndex.value] || Math.round(1000 / anim.fps)
  timer = setTimeout(advance, ms)
}

function advance() {
  timer = null
  const anim = current.value
  if (!anim || !playing.value) return
  const last = Math.min(anim.loopEnd, frames.value.length - 1)
  const first = Math.min(anim.loopStart, last)
  const next = nextSpriteFrame({
    index: frameIndex.value, direction: playbackDirection, first, last,
    looping: loop.value, mode: anim.loop,
  })
  frameIndex.value = next.index
  playbackDirection = next.direction
  playing.value = next.playing
  if (!next.playing) {
    draw()
    return
  }
  draw()
  scheduleNext()
}

function start() {
  if (!decoded.value) return
  if (!loop.value && frameIndex.value >= Math.min(current.value.loopEnd, frames.value.length - 1)) {
    frameIndex.value = 0
    playbackDirection = 1
    draw()
  }
  playing.value = true
  if (timer) clearTimeout(timer)
  scheduleNext()
}

function stopPlayback() {
  playing.value = false
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function togglePlay() {
  if (!decoded.value) {
    playing.value = !playing.value
    return
  }
  if (playing.value) stopPlayback()
  else start()
}

function step(delta) {
  if (!decoded.value) return
  stopPlayback()
  playbackDirection = 1
  const n = frames.value.length
  frameIndex.value = (frameIndex.value + delta + n) % n
  draw()
}

function onScrubPointer(event) {
  if (!decoded.value || !scrubRef.value) return
  if (event.type === 'pointermove' && event.buttons !== 1) return
  const rect = scrubRef.value.getBoundingClientRect()
  const n = frames.value.length
  const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0
  stopPlayback()
  playbackDirection = 1
  frameIndex.value = Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))))
  draw()
}

const tickCount = computed(() => (decoded.value ? frames.value.length : current.value?.frameCount || 0))
const headPercent = computed(() => {
  const n = tickCount.value
  return n > 1 ? (frameIndex.value / (n - 1)) * 100 : 0
})
const loopSpan = computed(() => {
  const anim = current.value
  const n = tickCount.value
  if (!anim || n <= 1) return { left: 0, width: 0 }
  const start = Math.min(anim.loopStart, n - 1)
  const end = Math.min(anim.loopEnd, n - 1)
  return { left: (start / (n - 1)) * 100, width: ((end - start) / (n - 1)) * 100 }
})

const readout = computed(() => {
  const anim = current.value
  const n = tickCount.value
  if (!anim || !n) return ''
  if (readoutMode.value === 'frames') return `${frameIndex.value + 1} / ${n}`
  const elapsed = anim.durations.slice(0, frameIndex.value).reduce((a, b) => a + b, 0)
  return `${(elapsed / 1000).toFixed(2)}s`
})

function toggleReadout() {
  readoutMode.value = readoutMode.value === 'frames' ? 'time' : 'frames'
  try { localStorage.setItem(makeProfileKey('frame-mode', FRAME_MODE_KEY), readoutMode.value) } catch { /* ignore */ }
}

function onKeydown(event) {
  if (event.code !== 'Space') return
  const target = event.target
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  if (!containerRef.value?.contains(document.activeElement) && !props.overlay) return
  event.preventDefault()
  togglePlay()
}

// --- sizing ---------------------------------------------------------------

function measureStage() {
  const el = stageRef.value
  if (!el) return
  stageSize.value = { width: el.clientWidth, height: el.clientHeight }
}

onMounted(() => {
  try {
    const stored = localStorage.getItem(makeProfileKey('frame-mode', FRAME_MODE_KEY))
    readoutMode.value = stored === 'time' ? 'time' : 'frames'
  } catch { /* ignore */ }
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(measureStage)
  }
  window.addEventListener('keydown', onKeydown)
  loadContent()
})

watch(stageRef, (el, prev) => {
  if (!resizeObserver) return
  if (prev) resizeObserver.unobserve(prev)
  if (el) {
    resizeObserver.observe(el)
    measureStage()
  }
})

watch(current, () => { decodeCurrent() })
watch(() => props.mediaId, () => { loadContent() })

onBeforeUnmount(() => {
  decodeToken += 1
  stopPlayback()
  releaseFrames()
  resizeObserver?.disconnect()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* Transport buttons share the slideshow's transport grammar (rounded-md, quiet at rest). */
.sprite-tbtn {
  @apply w-[26px] h-[26px] rounded-md border-none bg-transparent text-content-secondary cursor-pointer inline-flex items-center justify-center transition-colors hover:bg-white/[0.06] hover:text-content disabled:opacity-40 disabled:cursor-default;
}
</style>
