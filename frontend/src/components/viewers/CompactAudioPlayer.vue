<template>
  <!-- Short, wide waveform band — the same "audio reads as a waveform" treatment the
       library grid and slideshow use, shrunk to fit an input tile. -->
  <div class="relative w-full h-full bg-surface-raised overflow-hidden select-none">
    <!-- Waveform (click to seek) -->
    <div
      class="absolute inset-0 cursor-pointer"
      @click.stop="seekFromBand"
      ref="bandRef"
    >
      <img
        v-if="waveformUrl"
        :src="waveformUrl"
        class="w-full h-full object-fill opacity-90"
        alt="Audio waveform"
        @dragstart.prevent
      />
      <!-- Fallback when there's no waveform thumbnail (e.g. freshly uploaded
           reference audio that isn't a library item): a faux waveform. -->
      <div v-else class="w-full h-full flex items-center justify-center gap-[3px] px-4">
        <span
          v-for="(h, i) in fauxBars"
          :key="i"
          class="w-[3px] rounded-full bg-content-muted/40"
          :style="{ height: h + '%' }"
        />
      </div>

      <!-- Played-portion tint -->
      <div
        class="absolute inset-y-0 left-0 bg-blue-500/15 pointer-events-none"
        :style="{ width: progress + '%' }"
      />
      <!-- Playhead: only once playback has actually advanced — at progress 0 it's
           just a stray line pinned to the left edge. -->
      <div
        v-if="progress > 0"
        class="absolute top-0 bottom-0 w-0.5 bg-white/80 pointer-events-none"
        :style="{ left: progress + '%' }"
      />
    </div>

    <!-- Play / pause + time, bottom-left (clear of the tile's remove / order badges) -->
    <div class="absolute bottom-1.5 left-1.5 flex items-center gap-1.5 pointer-events-none">
      <button
        @click.stop="togglePlay"
        class="pointer-events-auto w-7 h-7 rounded-full bg-black/60 backdrop-blur-md text-white flex items-center justify-center hover:bg-black/75 transition-colors"
        :title="isPlaying ? 'Pause' : 'Play'"
      >
        <svg v-if="!isPlaying" class="w-4 h-4 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
        </svg>
        <svg v-else class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
          <path fill-rule="evenodd" d="M6.75 5.25a.75.75 0 01.75-.75H9a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H7.5a.75.75 0 01-.75-.75V5.25zm7.5 0A.75.75 0 0115 4.5h1.5a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H15a.75.75 0 01-.75-.75V5.25z" clip-rule="evenodd" />
        </svg>
      </button>
      <span class="px-1.5 py-0.5 rounded bg-black/60 backdrop-blur-md text-[10px] text-white tabular-nums leading-none">
        {{ formatTime(currentTime) }} / {{ formatTime(effectiveDuration) }}
      </span>
    </div>

    <audio
      ref="audioRef"
      :src="src"
      class="hidden"
      preload="metadata"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMetadata"
      @durationchange="onDurationChange"
      @ended="isPlaying = false"
      @play="isPlaying = true"
      @pause="isPlaying = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, watchEffect, onUnmounted } from 'vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaPlayback, useManagedMediaElement } from '../../composables/useMediaPlayback'

const props = defineProps<{
  src: string
  mediaId?: number
  duration?: number | null
}>()

const { getThumbnailUrl } = useMediaApi()

const waveformUrl = computed(() => (props.mediaId ? getThumbnailUrl(props.mediaId, 800) : ''))

// A static, evenly-pseudo-random bar pattern for the no-thumbnail fallback.
const fauxBars = [38, 62, 30, 80, 52, 70, 44, 92, 58, 34, 74, 48, 66, 40, 84, 56, 28, 72, 50, 60, 36, 78, 46, 64, 32, 88, 54, 42]

const audioRef = ref<HTMLAudioElement | null>(null)
const bandRef = ref<HTMLElement | null>(null)

// No volume UI of its own — follows the global audio channel, and joins the
// playback registry (pause on KeepAlive deactivate, teardown on unmount).
const { audioMuted, audioVolume } = useMediaPlayback()
useManagedMediaElement(audioRef)
watchEffect(() => {
  const a = audioRef.value
  if (!a) return
  a.muted = audioMuted.value
  a.volume = audioVolume.value
})
const isPlaying = ref(false)
const currentTime = ref(0)
const audioDuration = ref(props.duration || 0)

const effectiveDuration = computed(() => props.duration || audioDuration.value)
const progress = computed(() => {
  const d = effectiveDuration.value
  return d > 0 ? Math.min(100, (currentTime.value / d) * 100) : 0
})

let rafId: number | null = null

// The `timeupdate` event only fires a few times a second, which makes the
// playhead visibly step across a short wide band. Poll currentTime on every
// frame while playing instead, for a smooth sweep.
function tick() {
  if (audioRef.value) currentTime.value = audioRef.value.currentTime
  if (isPlaying.value) rafId = requestAnimationFrame(tick)
}

function stopTicking() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

watch(isPlaying, (playing) => {
  stopTicking()
  if (playing) rafId = requestAnimationFrame(tick)
})

function togglePlay() {
  const a = audioRef.value
  if (!a) return
  if (isPlaying.value) a.pause()
  else a.play()
}

function seekFromBand(e: MouseEvent) {
  const a = audioRef.value
  const d = effectiveDuration.value
  if (!a || d <= 0 || !bandRef.value) return
  const rect = bandRef.value.getBoundingClientRect()
  const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  a.currentTime = pos * d
}

function onTimeUpdate() {
  if (audioRef.value) currentTime.value = audioRef.value.currentTime
}
function onLoadedMetadata() {
  if (audioRef.value && isFinite(audioRef.value.duration)) audioDuration.value = audioRef.value.duration
}
function onDurationChange() {
  if (audioRef.value && isFinite(audioRef.value.duration)) audioDuration.value = audioRef.value.duration
}

function formatTime(seconds: number): string {
  if (!seconds || isNaN(seconds)) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

onUnmounted(() => {
  stopTicking()
  audioRef.value?.pause()
})
</script>
