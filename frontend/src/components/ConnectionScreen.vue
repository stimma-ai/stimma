<template>
  <!-- Full-window, not a page. The sidebar and content of a dead backend are
       undefined, so App.vue v-ifs the router view away rather than leaving
       stale chrome behind this. Modeled on the PIN lock screen. -->
  <div class="fixed inset-0 z-top bg-surface-overlay">
    <!-- Minimal top bar: window controls region plus the chip, nothing else. -->
    <div class="absolute top-0 left-0 right-0 h-14" data-tauri-drag-region />
    <div class="absolute top-4 right-4">
      <DeviceChip />
    </div>

    <div class="absolute inset-0 flex flex-col items-center justify-center gap-6 px-6 pointer-events-none">
      <div class="flex flex-col items-center gap-2 pointer-events-auto">
        <!-- Centered device identity: on a satellite this is the only thing
             telling you which machine you are waiting for. -->
        <div class="text-lg font-semibold text-content">{{ deviceName }}</div>
        <!-- The connecting state can last a while on purpose (main keeps
             sweeping before it admits a device is unreachable), so it has to
             read as progress rather than a stall. -->
        <div class="text-sm text-content-secondary min-h-[1.25rem] flex items-center gap-2">
          <Spinner v-if="restartExpected || connectionState === 'connecting'" size="sm" />
          <span>{{ statusLine }}</span>
        </div>
        <p v-if="restartExpected" class="text-xs text-content-tertiary">
          {{ restartTakingLonger ? 'Still waiting for the server. Reconnecting automatically.' : 'Your library will reconnect automatically. This can take a couple of minutes.' }}
        </p>
      </div>

      <div v-if="!restartExpected || restartTakingLonger" class="flex items-center gap-3 pointer-events-auto">
        <button
          class="h-8 px-3 rounded-md text-[13px] bg-overlay-subtle text-content transition-colors cursor-pointer hover:bg-overlay-light"
          :disabled="connectionState === 'connecting'"
          :class="connectionState === 'connecting' ? 'opacity-60 cursor-not-allowed' : ''"
          @click="retry"
        >
          Retry
        </button>

        <!-- Explicit, never automatic: a satellite must not silently drop the
             user into its own empty local install. -->
        <button
          v-if="connectionState === 'unreachable'"
          class="h-8 px-3 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
          @click="useLocalServer"
        >
          Use local server
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useMultiDevice } from '../composables/useMultiDevice'
import DeviceChip from './DeviceChip.vue'
import Spinner from './ui/Spinner.vue'
import { useServerUpdater } from '../composables/useServerUpdater'

const { connectionState, activeDeviceName, retry, refresh, useLocalServer } = useMultiDevice()
const { restartExpected, restartTakingLonger } = useServerUpdater()

const deviceName = computed(() => activeDeviceName.value)

const statusLine = computed(() =>
  restartExpected.value ? `Restarting ${deviceName.value}…` : connectionState.value === 'unreachable'
    ? `${deviceName.value} is unreachable`
    : `Connecting to ${deviceName.value}…`,
)

// Auto-retry, with the manual button always visible. Slow enough not to
// hammer a sleeping machine, fast enough that waking one feels immediate.
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
