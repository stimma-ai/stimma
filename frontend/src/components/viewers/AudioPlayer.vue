<template>
  <div class="relative flex flex-col items-center justify-center w-full h-full bg-surface-raised p-8">
    <!-- Waveform visualization -->
    <div
      class="w-full max-w-2xl h-40 rounded-lg mb-8 overflow-hidden relative cursor-pointer"
      @click="seekFromWaveform"
      ref="waveformContainerRef"
    >
      <img
        v-if="mediaId"
        :src="waveformUrl"
        class="w-full h-full object-fill"
        alt="Audio waveform"
        @dragstart.prevent
      />
      <!-- Position indicator -->
      <div
        class="absolute top-0 bottom-0 w-0.5 bg-white shadow-lg"
        :style="{ left: `${progress}%` }"
      />
    </div>

    <!-- Title -->
    <h2 v-if="title" class="text-content text-xl font-semibold mb-2">{{ title }}</h2>
    <p v-if="subtitle" class="text-content-tertiary text-sm mb-6">{{ subtitle }}</p>

    <!-- Audio element -->
    <audio
      ref="audioRef"
      :src="src"
      class="hidden"
      preload="auto"
      loop
      @timeupdate="handleTimeUpdate"
      @loadedmetadata="handleLoadedMetadata"
      @durationchange="handleDurationChange"
      @canplay="handleCanPlay"
      @play="isPlaying = true"
      @pause="isPlaying = false"
    />

    <!-- Progress bar -->
    <div class="w-full max-w-2xl mb-4">
      <div
        class="w-full h-2 bg-overlay-light rounded-full cursor-pointer overflow-hidden"
        @click="seek"
      >
        <div
          class="h-full bg-gradient-to-r from-purple-500 to-cyan-400 transition-all"
          :style="{ width: `${progress}%` }"
        />
      </div>
      <div class="flex justify-between mt-1 text-xs text-content-tertiary">
        <span>{{ formatTime(currentTime) }}</span>
        <span>{{ formatTime(effectiveDuration) }}</span>
      </div>
    </div>

    <!-- Controls -->
    <div class="flex items-center gap-4">
      <button
        @click="skipBack"
        class="w-10 h-10 rounded-full bg-overlay-light text-content flex items-center justify-center hover:bg-overlay-strong transition-colors"
        title="Skip back 10s"
      >
        <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
        </svg>
      </button>

      <button
        @click="togglePlay"
        class="w-16 h-16 rounded-full bg-gradient-to-r from-purple-500 to-cyan-400 text-white flex items-center justify-center hover:opacity-90 transition-opacity"
      >
        <svg v-if="!isPlaying" class="w-8 h-8 ml-1" fill="currentColor" viewBox="0 0 24 24">
          <path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
        </svg>
        <svg v-else class="w-8 h-8" fill="currentColor" viewBox="0 0 24 24">
          <path fill-rule="evenodd" d="M6.75 5.25a.75.75 0 01.75-.75H9a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H7.5a.75.75 0 01-.75-.75V5.25zm7.5 0A.75.75 0 0115 4.5h1.5a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H15a.75.75 0 01-.75-.75V5.25z" clip-rule="evenodd" />
        </svg>
      </button>

      <button
        @click="skipForward"
        class="w-10 h-10 rounded-full bg-overlay-light text-content flex items-center justify-center hover:bg-overlay-strong transition-colors"
        title="Skip forward 10s"
      >
        <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 15l6-6m0 0l-6-6m6 6H9a6 6 0 000 12h3" />
        </svg>
      </button>
    </div>

    <!-- Volume control (bottom right) -->
    <div class="absolute bottom-6 right-6 flex items-center gap-2">
      <button
        @click="toggleMute"
        class="w-8 h-8 rounded-full text-content-tertiary flex items-center justify-center hover:text-content transition-colors"
      >
        <svg v-if="volume > 0" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
        </svg>
        <svg v-else class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.506-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
        </svg>
      </button>
      <input
        type="range"
        v-model="volume"
        min="0"
        max="1"
        step="0.1"
        class="w-20 accent-purple-500"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { makeProfileKey } from '../../utils/storageKeys'

const VOLUME_KEY = makeProfileKey('audio_player', 'volume')

function getSavedVolume() {
  const saved = localStorage.getItem(VOLUME_KEY)
  if (saved !== null) {
    const val = parseFloat(saved)
    if (!isNaN(val) && val >= 0 && val <= 1) return val
  }
  return 1
}

const props = defineProps({
  src: {
    type: String,
    required: true
  },
  mediaId: {
    type: Number,
    required: false
  },
  duration: {
    type: Number,
    required: false,
    default: null
  },
  title: String,
  subtitle: String,
  autoplay: {
    type: Boolean,
    default: false
  }
})

const { getThumbnailUrl } = useMediaApi()

const waveformUrl = computed(() => {
  if (!props.mediaId) return ''
  return getThumbnailUrl(props.mediaId, 800)
})

const audioRef = ref(null)
const waveformContainerRef = ref(null)
const isPlaying = ref(false)
const currentTime = ref(0)
// Use prop duration if provided (from ffprobe), otherwise will be set from audio element
const duration = ref(props.duration || 0)
const volume = ref(getSavedVolume())
const progress = ref(0)
const canPlay = ref(false)
const pendingAutoplay = ref(false)

// Authoritative duration - prefer props.duration (from ffprobe) over browser's estimate
const effectiveDuration = computed(() => props.duration || duration.value)

function togglePlay() {
  if (audioRef.value) {
    if (isPlaying.value) {
      audioRef.value.pause()
    } else {
      audioRef.value.play()
    }
  }
}

function toggleMute() {
  volume.value = volume.value > 0 ? 0 : 1
}

function skipBack() {
  if (audioRef.value) {
    audioRef.value.currentTime = Math.max(0, audioRef.value.currentTime - 10)
  }
}

function skipForward() {
  if (audioRef.value) {
    audioRef.value.currentTime = Math.min(effectiveDuration.value, audioRef.value.currentTime + 10)
  }
}

function seek(e) {
  const audio = audioRef.value
  const dur = effectiveDuration.value
  if (audio && dur > 0) {
    const rect = e.currentTarget.getBoundingClientRect()
    const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    audio.currentTime = pos * dur
  }
}

function seekFromWaveform(e) {
  const audio = audioRef.value
  const dur = effectiveDuration.value
  if (audio && dur > 0 && waveformContainerRef.value) {
    const rect = waveformContainerRef.value.getBoundingClientRect()
    const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    audio.currentTime = pos * dur
  }
}

function handleTimeUpdate() {
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
    const dur = effectiveDuration.value
    progress.value = dur > 0 ? (currentTime.value / dur) * 100 : 0
  }
}

function handleLoadedMetadata() {
  if (audioRef.value && isFinite(audioRef.value.duration)) {
    duration.value = audioRef.value.duration
  }
}

function handleDurationChange() {
  // Duration can change as more of the file loads (especially for streaming/large files)
  if (audioRef.value && isFinite(audioRef.value.duration)) {
    duration.value = audioRef.value.duration
  }
}

function handleCanPlay() {
  canPlay.value = true
  if (pendingAutoplay.value) {
    pendingAutoplay.value = false
    audioRef.value?.play()
  }
}

function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

watch(volume, (v) => {
  if (audioRef.value) {
    audioRef.value.volume = v
  }
  localStorage.setItem(VOLUME_KEY, String(v))
})

onMounted(() => {
  // Set initial volume from saved preference
  if (audioRef.value) {
    audioRef.value.volume = volume.value
  }

  if (props.autoplay) {
    if (canPlay.value && audioRef.value) {
      // Already ready, play immediately
      audioRef.value.play()
    } else {
      // Wait for canplay event
      pendingAutoplay.value = true
    }
  }
})

onUnmounted(() => {
  if (audioRef.value) {
    audioRef.value.pause()
  }
})
</script>
