<template>
  <!-- Full-window, not a page. The sidebar and content of a dead backend are
       undefined, so App.vue v-ifs the router view away rather than leaving
       stale chrome behind this. Modeled on the PIN lock screen. -->
  <div class="fixed inset-0 z-top bg-surface-overlay">
    <!-- Minimal top bar: window controls region plus the chip, nothing else. -->
    <div class="absolute top-0 left-0 right-0 h-14" data-tauri-drag-region />
    <div class="absolute top-4 right-4 z-10">
      <DeviceChip ref="chip" />
    </div>

    <div class="flex h-full items-center justify-center overflow-y-auto px-6 pt-safe pb-safe">
      <div class="flex w-full max-w-sm flex-col items-center py-8 text-center">
        <img class="connection-logo motion-reduce:animate-none" src="/logo.svg" alt="" />
        <h1 class="mt-6 max-w-full break-words font-brand text-lg font-semibold text-content">{{ deviceName }}</h1>
        <p class="mt-2 text-sm text-content-secondary" role="status">{{ statusLine }}</p>
        <Button variant="link" class="mt-4 min-h-11 shrink-0" @click="chip?.openMenu()">Choose another server</Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useMultiDevice } from '../composables/useMultiDevice'
import DeviceChip from './DeviceChip.vue'
import Button from './ui/Button.vue'
import { useServerUpdater } from '../composables/useServerUpdater'

const { connectionState, activeDeviceName, retry, refresh } = useMultiDevice()
const { restartExpected, restartTakingLonger } = useServerUpdater()

const chip = ref(null)
const deviceName = computed(() => activeDeviceName.value)

// Two beats per situation: what is happening, then (once it has been a while)
// that we are still at it. The unreachable state is not a distinct message —
// the auto-retry below keeps trying, so to the user it is just a long connect.
const statusLine = computed(() => {
  if (restartExpected.value) {
    return restartTakingLonger.value ? `Still waiting for ${deviceName.value}…` : 'Restarting after the update…'
  }
  return connectionState.value === 'unreachable'
    ? `Still waiting for ${deviceName.value}…`
    : `Connecting to ${deviceName.value}…`
})

// Auto-retry for as long as the screen is showing. Slow enough not to hammer
// a sleeping machine, fast enough that waking one feels immediate.
const RETRY_INTERVAL_MS = 5000
let timer = null
let autoRetryInFlight = false

onMounted(() => {
  timer = setInterval(async () => {
    if (connectionState.value !== 'unreachable' || autoRetryInFlight) return
    autoRetryInFlight = true
    // Nothing is pushing us roster changes here — there is no app websocket
    // while the window has no backend — so re-read the roster before the
    // retry. That is also how a device's routes get refreshed after it moves.
    try {
      await refresh()
      if (connectionState.value === 'unreachable') await retry()
    } finally {
      autoRetryInFlight = false
    }
  }, RETRY_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
/* Same swing as the launch screen (startup-pendulum lives in style.css),
   sized for the card. */
.connection-logo {
  width: 48px;
  height: 48px;
  animation: startup-pendulum 2.4s ease-in-out infinite;
  transform-origin: center;
}
</style>
