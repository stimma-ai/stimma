<template>
  <!-- Filmstrip scrubber: the track is a frame-strip montage of the video with a
       live playhead, same treatment as the prep frame picker. The host owns the
       outer chrome (position, background), passed through as attrs. -->
  <div class="flex items-center gap-2 select-none" @mousedown.stop @dblclick.stop @click.stop>
    <!-- Play / Pause -->
    <button
      type="button"
      @click="togglePlayback"
      class="bg-transparent border-none text-white/60 cursor-pointer p-1 flex items-center justify-center rounded-md transition-all hover:bg-white/10 hover:text-white flex-shrink-0"
      :title="paused ? 'Play video' : 'Pause video'"
    >
      <PlayIcon v-if="paused" class="w-5 h-5" />
      <PauseIcon v-else class="w-5 h-5" />
    </button>

    <!-- Filmstrip track -->
    <div
      class="relative flex-1 min-w-0 h-[34px] rounded-md overflow-hidden border border-white/10 bg-black/30 cursor-pointer select-none touch-none"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @dragstart.prevent
    >
      <img
        v-if="stripUrl && !stripFailed"
        :src="stripUrl"
        @load="stripReady = true"
        @error="stripFailed = true"
        class="absolute inset-0 w-full h-full object-fill pointer-events-none transition-opacity duration-300"
        :class="{ 'opacity-0': !stripReady }"
        draggable="false"
      />
      <!-- skeleton cells while the strip renders (best-effort; scrubbing works regardless) -->
      <div
        v-if="stripUrl && !stripFailed && !stripReady"
        class="absolute inset-0 flex gap-px p-px animate-pulse pointer-events-none"
      >
        <div v-for="i in 12" :key="i" class="flex-1 rounded-[3px] bg-white/[0.07]"></div>
      </div>
      <!-- progress reads as a dim over the not-yet-played region (no color haze) -->
      <div
        class="absolute inset-y-0 right-0 bg-black/35 pointer-events-none"
        :style="{ width: (100 - percent) + '%' }"
      ></div>
      <div
        class="absolute top-0 bottom-0 w-0.5 bg-blue-400 pointer-events-none"
        style="box-shadow: 0 0 6px rgba(96,165,250,.8)"
        :style="{ left: percent + '%' }"
      ></div>
    </div>

    <!-- Readout. Click toggles time ↔ frames (persisted, like the prep frame picker).
         Fixed min-width + right alignment: the ticking digits must not reflow the
         bar, or the text moves out from under the cursor mid-click. -->
    <button
      type="button"
      @pointerdown.stop="toggleDisplayMode"
      :title="displayMode === 'frames' ? 'Show time' : 'Show frame number'"
      class="bg-transparent border-none text-[11px] text-blue-400 font-medium tabular-nums hover:text-blue-300 hover:bg-white/10 rounded-md cursor-pointer whitespace-nowrap flex-shrink-0 px-1.5 py-1 min-w-[96px] text-right"
    ><span class="pointer-events-none">{{ label }}</span></button>

    <slot />
  </div>
</template>

<script setup lang="ts">
import { PlayIcon, PauseIcon } from '@heroicons/vue/24/solid'
import type { VideoTransport } from '../../composables/useVideoTransport'

const props = defineProps<{ transport: VideoTransport }>()

// The transport object is created once per host, so destructuring its refs
// here keeps them reactive and auto-unwrapped in the template.
const {
  paused, stripUrl, stripReady, stripFailed, percent, label, displayMode,
  togglePlayback, toggleDisplayMode, onPointerDown, onPointerMove, onPointerUp, onPointerCancel,
} = props.transport
</script>
