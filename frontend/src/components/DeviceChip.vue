<template>
  <!-- Hidden entirely until the account has offered a second computer, so
       single-machine users see zero footprint. Note this does NOT depend on
       whether THIS install serves: pointing a laptop at the studio machine
       must not require offering the laptop in return. -->
  <div v-if="hasOtherDevices" class="relative device-menu">
    <!-- Ghost trigger, matching the profile picker: bordered+filled chips
         aren't Atelier chrome; the menu carries the affordance. -->
    <button
      data-tour="device-chip"
      class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
      @click="toggleMenu"
      :title="isRemote ? `On ${activeDeviceName}` : 'This computer'"
    >
      <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="statusDotClass" />
      <span class="max-w-[140px] truncate">{{ activeDeviceName }}</span>
      <svg
        class="w-3 h-3 flex-shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="2"
        stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
      </svg>
    </button>

    <transition name="menu">
      <div
        v-if="menuOpen"
        class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu min-w-[300px] overflow-hidden"
      >
        <div class="py-1">
          <DeviceRow
            :label="selfName || 'This computer'"
            :channel="selfChannel"
            :sandbox="selfSandbox"
            :detail="selfName ? 'this computer' : ''"
            :selected="!isRemote"
            @select="pick(LOCAL_DEVICE)"
          />
          <DeviceRow
            v-for="device in onlineDevices"
            :key="device.deviceId"
            :label="device.name"
            :channel="device.channel"
            :sandbox="device.sandbox"
            :selected="activeDeviceId === device.deviceId"
            @select="pick(device.deviceId)"
          />
        </div>

        <!-- Offered but not up. Behind a disclosure so the everyday list is
             only what you can actually reach, but still present, because a
             computer vanishing from the menu is worse than a quiet count. -->
        <div v-if="offlineDevices.length" class="border-t border-edge-subtle">
          <button
            class="w-full flex items-center gap-1.5 px-3 py-2 text-[11px] text-content-tertiary transition-colors cursor-pointer hover:text-content-secondary"
            @click="showOffline = !showOffline"
          >
            <svg
              class="w-3 h-3 flex-shrink-0 transition-transform duration-150"
              :class="showOffline ? 'rotate-90' : ''"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="2"
              stroke="currentColor"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
            </svg>
            <span>Offline</span>
            <span class="font-mono tabular-nums">{{ offlineDevices.length }}</span>
          </button>
          <div v-if="showOffline" class="pb-1">
            <DeviceRow
              v-for="device in offlineDevices"
              :key="device.deviceId"
              :label="device.name"
              :channel="device.channel"
              :sandbox="device.sandbox"
              :detail="lastSeenLabel(device)"
              muted
              :selected="activeDeviceId === device.deviceId"
              @select="pick(device.deviceId)"
            />
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useMultiDevice } from '../composables/useMultiDevice'
import DeviceRow from './DeviceRow.vue'

const {
  LOCAL_DEVICE,
  activeDeviceId,
  onlineDevices,
  offlineDevices,
  hasOtherDevices,
  activeDeviceName,
  isRemote,
  connectionState,
  selfName,
  selfChannel,
  selfSandbox,
  lastSeenLabel,
  switchToDevice,
  refresh,
} = useMultiDevice()

const menuOpen = ref(false)
const showOffline = ref(false)

// Status colours are status-only per the design language: blue-500 is never
// an interactive accent, so it is the right token for "connected".
const statusDotClass = computed(() => {
  if (connectionState.value === 'unreachable') return 'bg-red-500'
  if (connectionState.value === 'connecting') return 'bg-amber-500'
  return isRemote.value ? 'bg-blue-500' : 'bg-content-muted'
})

function toggleMenu() {
  menuOpen.value = !menuOpen.value
  // Presence can have moved while the menu was shut; re-read on open rather
  // than polling for a menu nobody is looking at.
  if (menuOpen.value) void refresh()
}

async function pick(deviceId) {
  menuOpen.value = false
  await switchToDevice(deviceId)
}

function onDocumentClick(event) {
  if (!event.target.closest('.device-menu')) menuOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  void refresh()
})
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>
