<template>
  <!-- Full-window, not a page. The sidebar and content of a dead backend are
       undefined, so App.vue v-ifs the router view away rather than leaving
       stale chrome behind this. Modeled on the PIN lock screen. -->
  <div class="fixed inset-0 z-top bg-surface-overlay">
    <!-- Minimal top bar: window controls region plus the chip, nothing else. -->
    <div class="absolute top-0 left-0 right-0 h-14" data-tauri-drag-region />
    <div class="absolute top-4 right-4">
      <DeviceChip ref="chip" />
    </div>

    <div class="absolute inset-0 flex items-center justify-center px-6">
      <!-- The server is the subject: its name and one line of status, with the
           launch screen's swinging logo so a restart reads as Stimma coming
           back rather than an error. There is no retry button because the app
           retries continuously for as long as this screen is up; the only
           real choice is a different server, and that lives at the bottom. -->
      <div class="flex flex-col items-center rounded-[14px] border border-edge bg-surface px-11 pt-[30px] pb-[26px] min-w-[280px]">
        <img class="connection-logo" src="/logo.svg" alt="" />
        <div class="mt-4 text-[15px] font-semibold text-content">{{ deviceName }}</div>
        <div class="mt-1 text-[13px] text-content-secondary">{{ statusLine }}</div>
      </div>
    </div>

    <button
      class="absolute bottom-4 left-1/2 -translate-x-1/2 text-[11.5px] text-content-tertiary transition-colors cursor-pointer hover:text-content-secondary bg-transparent border-none"
      @click="chip?.openMenu()"
    >
      Choose another server
    </button>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useMultiDevice } from '../composables/useMultiDevice'
import DeviceChip from './DeviceChip.vue'
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
