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
        <div class="text-sm text-content-secondary min-h-[1.25rem]">{{ statusLine }}</div>
      </div>

      <div class="flex items-center gap-3 pointer-events-auto">
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
          @click="useThisComputer"
        >
          Use this computer
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useMultiDevice } from '../composables/useMultiDevice'
import DeviceChip from './DeviceChip.vue'

const { connectionState, activeDeviceName, retry, useThisComputer } = useMultiDevice()

const deviceName = computed(() => activeDeviceName.value)

const statusLine = computed(() =>
  connectionState.value === 'unreachable'
    ? `${deviceName.value} is unreachable`
    : `Connecting to ${deviceName.value}…`,
)

// Auto-retry, with the manual button always visible. Slow enough not to
// hammer a sleeping machine, fast enough that waking one feels immediate.
const RETRY_INTERVAL_MS = 5000
let timer = null

onMounted(() => {
  timer = setInterval(() => {
    if (connectionState.value === 'unreachable') void retry()
  }, RETRY_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>
