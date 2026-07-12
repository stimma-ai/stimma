<template>
  <!-- Click speaker to mute/unmute; hover for the volume popup. Bound to a
       persisted video channel: the default one (shared with the slideshow)
       or, when `scope` is set, an independent per-scope channel. -->
  <div class="relative" @mouseenter="onHoverEnter" @mouseleave="onHoverLeave">
    <button
      @click.stop="toggleVideoMute"
      :class="[
        'w-8 h-8 rounded-lg flex items-center justify-center transition-all',
        videoMuted
          ? 'bg-black/40 hover:bg-black/60 text-white/50 hover:text-white'
          : 'bg-black/40 hover:bg-black/60 text-[#ec4899] hover:text-[#f472b6]'
      ]"
      title="Mute/unmute — hover for volume"
    >
      <SpeakerWaveIcon v-if="!videoMuted && videoVolume > 0.5" class="w-5 h-5" />
      <SpeakerWaveIcon v-else-if="!videoMuted && videoVolume > 0" class="w-5 h-5 scale-90" />
      <SpeakerXMarkIcon v-else class="w-5 h-5" />
    </button>
    <!-- Volume popup with slider + mute -->
    <div
      v-if="showSlider"
      class="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 px-2 py-2 flex flex-col items-center gap-2 bg-black/70 backdrop-blur-xl rounded-xl border border-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.4)] z-50"
      @mousedown.stop
      @click.stop
    >
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        :value="videoVolume"
        @input="handleVolumeInput"
        class="volume-slider-vertical h-24"
        orient="vertical"
      />
      <button
        @click.stop="toggleVideoMute"
        :class="[
          'bg-transparent border-none cursor-pointer p-1 flex items-center justify-center rounded-md transition-all',
          videoMuted ? 'text-white/40 hover:text-white' : 'text-[#ec4899] hover:text-[#f472b6]'
        ]"
      >
        <SpeakerXMarkIcon v-if="videoMuted" class="w-4 h-4" />
        <SpeakerWaveIcon v-else class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import { SpeakerWaveIcon, SpeakerXMarkIcon } from '@heroicons/vue/24/solid'
import { useMediaPlayback, useScopedVideoPlayback } from '../../composables/useMediaPlayback'

// scope: name of an independent persisted channel (useScopedVideoPlayback);
// omit to control the default video channel shared with the slideshow.
const props = defineProps<{ scope?: string }>()

const { muted: videoMuted, volume: videoVolume, toggleMute: toggleVideoMute } = props.scope
  ? useScopedVideoPlayback(props.scope)
  : (() => {
      const { videoMuted: muted, videoVolume: volume, toggleVideoMute: toggleMute } = useMediaPlayback()
      return { muted, volume, toggleMute }
    })()

const showSlider = ref(false)
let hoverTimer: ReturnType<typeof setTimeout> | null = null

function onHoverEnter() {
  if (hoverTimer) {
    clearTimeout(hoverTimer)
    hoverTimer = null
  }
  showSlider.value = true
}

function onHoverLeave() {
  // Small delay so moving the cursor across the gap into the popup doesn't close it.
  if (hoverTimer) clearTimeout(hoverTimer)
  hoverTimer = setTimeout(() => {
    showSlider.value = false
    hoverTimer = null
  }, 200)
}

function handleVolumeInput(event: Event) {
  const val = parseFloat((event.target as HTMLInputElement).value)
  videoVolume.value = val
  videoMuted.value = val === 0
}

onBeforeUnmount(() => {
  if (hoverTimer) clearTimeout(hoverTimer)
})
</script>

<style scoped>
.volume-slider-vertical {
  -webkit-appearance: none;
  writing-mode: vertical-lr;
  direction: rtl;
  appearance: none;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 9999px;
  width: 4px;
}
.volume-slider-vertical::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}
</style>
