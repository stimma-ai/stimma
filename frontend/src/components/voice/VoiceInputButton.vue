<template>
  <div v-if="supported" class="relative flex items-center">
    <!-- Mic button: press-and-hold to talk, or tap to toggle latched recording -->
    <button
      type="button"
      :title="title"
      @pointerdown="onDown"
      @pointerup="onUp"
      @pointerleave="onLeave"
      class="relative w-8 h-8 flex items-center justify-center rounded-full transition-colors select-none"
      :class="buttonClass"
    >
      <!-- Downloading / finalizing: spinner -->
      <Spinner v-if="isBusy" size="md" />

      <!-- Recording: stop square -->
      <svg v-else-if="isRecording" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
        <rect x="6" y="6" width="12" height="12" rx="2" />
      </svg>

      <!-- Idle: microphone -->
      <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" :class="iconClass">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z" />
      </svg>

      <!-- Recording pulse dot -->
      <span
        v-if="isRecording"
        class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-red-500 animate-pulse-soft"
      />
    </button>

    <!-- Download percentage -->
    <span v-if="state === 'downloading'" class="ml-1 text-[11px] tabular-nums text-content-muted">
      {{ downloadLabel }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useVoiceInput } from '../../composables/useVoiceInput'
import Spinner from '../ui/Spinner.vue'

const props = withDefaults(
  defineProps<{
    getText: () => string
    setText: (text: string) => void
    focus?: () => void
    iconClass?: string
    /** Telemetry surface: main_chat | flow_chat | prompt_agent | feedback */
    surface?: string
  }>(),
  { iconClass: 'w-5 h-5', surface: 'main_chat' }
)

const {
  supported,
  state,
  error,
  isRecording,
  isBusy,
  downloaded,
  downloadTotal,
  start,
  stop,
  cancel,
  handleInputKeydown,
  handleInputKeyup,
} = useVoiceInput({
  getText: () => props.getText(),
  setText: (t: string) => props.setText(t),
  focus: () => props.focus?.(),
  surface: props.surface,
})

// Let the host input wire Space-to-dictate to its text field.
// `cancel` lets hosts abort dictation when their input blurs mid-hold —
// otherwise the space keyup never arrives and the mic keeps recording.
defineExpose({ handleInputKeydown, handleInputKeyup, cancel })

const HOLD_MS = 400
let downAt = 0
const pointerDown = ref(false)

async function onDown(e: PointerEvent) {
  e.preventDefault() // keep focus/caret in the text field
  if (isBusy.value) return
  if (isRecording.value) {
    await stop()
    return
  }
  downAt = Date.now()
  pointerDown.value = true
  await start()
}

async function onUp() {
  if (!pointerDown.value) return
  pointerDown.value = false
  // A genuine hold stops on release; a quick tap latches (stays recording).
  if (isRecording.value && Date.now() - downAt > HOLD_MS) await stop()
}

async function onLeave() {
  if (!pointerDown.value) return
  pointerDown.value = false
  if (isRecording.value && Date.now() - downAt > HOLD_MS) await stop()
}

const buttonClass = computed(() => {
  if (isRecording.value) return 'bg-red-500/15 text-red-400 hover:bg-red-500/25'
  if (state.value === 'error') return 'text-red-400 hover:bg-overlay-subtle'
  return 'text-content-muted hover:text-content-secondary hover:bg-overlay-subtle'
})

const title = computed(() => {
  if (state.value === 'error') return error.value || 'Voice input error'
  if (state.value === 'downloading') return `Downloading voice model… ${downloadLabel.value}`
  if (state.value === 'finalizing') return 'Transcribing…'
  if (isRecording.value) return 'Recording — release or tap to stop'
  return 'Hold to talk — or hold the spacebar in the text box to dictate'
})

const downloadLabel = computed(() => {
  if (!downloadTotal.value) {
    return downloaded.value > 0 ? `${(downloaded.value / 1e6).toFixed(0)}MB` : '…'
  }
  return `${Math.round((downloaded.value / downloadTotal.value) * 100)}%`
})
</script>
