<template>
  <!-- One-shot sound audition for ambient looping video. The owner drives the
       actual audible pass and reports it via `active`/`progress`; this control
       is the button (click = play one pass with sound / stop) plus the hover
       popover for the audition volume level. There is no persistent mute state,
       so the speaker icon is never slashed — a draining progress ring while the
       pass plays shows that the sound ends on its own. -->
  <div class="relative" @mouseenter="onHoverEnter" @mouseleave="onHoverLeave">
    <button
      @click.stop="emit('toggle')"
      :class="[
        'relative w-8 h-8 rounded backdrop-blur-sm flex items-center justify-center bg-black/55 transition-all',
        active ? 'text-accent hover:text-accent/80' : 'text-white/50 hover:bg-black/70 hover:text-white'
      ]"
      :title="active ? 'Stop sound' : 'Play sound once — hover for volume'"
    >
      <SpeakerWaveIcon class="w-icon-canvas h-icon-canvas" />
      <svg v-if="active" class="absolute inset-0 w-8 h-8 -rotate-90 pointer-events-none" viewBox="0 0 32 32">
        <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" stroke-opacity="0.25" stroke-width="2" />
        <circle
          cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
          :stroke-dasharray="CIRCUMFERENCE"
          :stroke-dashoffset="CIRCUMFERENCE * Math.min(1, Math.max(0, progress))"
        />
      </svg>
    </button>
    <!-- Volume popup: level only (applies to audible passes). No mute button —
         the floor keeps "play sound once" from being a silent no-op. -->
    <div
      v-if="showSlider"
      class="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 px-2 py-2 flex flex-col items-center bg-black/70 backdrop-blur-xl rounded-lg border border-white/10 shadow-[0_4px_20px_rgba(0,0,0,0.4)] z-menu"
      @mousedown.stop
      @click.stop
    >
      <input
        type="range"
        min="0.05"
        max="1"
        step="0.05"
        :value="volume"
        @input="handleVolumeInput"
        class="volume-slider-vertical h-24"
        orient="vertical"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import { SpeakerWaveIcon } from '@heroicons/vue/24/solid'
import { useMediaPlayback, useScopedVideoPlayback } from '../../composables/useMediaPlayback'

const CIRCUMFERENCE = 2 * Math.PI * 14.5

// scope: name of an independent persisted volume channel (useScopedVideoPlayback);
// omit to use the default video channel shared with the slideshow.
// active/progress: whether an audible pass is playing and how far along it is (0..1).
const props = defineProps<{ scope?: string; active: boolean; progress: number }>()
const emit = defineEmits<{ (e: 'toggle'): void }>()

const { volume } = props.scope
  ? useScopedVideoPlayback(props.scope)
  : (() => {
      const { videoVolume } = useMediaPlayback()
      return { volume: videoVolume }
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
  volume.value = Math.max(0.05, parseFloat((event.target as HTMLInputElement).value))
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
