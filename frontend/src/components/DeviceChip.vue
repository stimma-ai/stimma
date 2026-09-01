<template>
  <!-- Hidden entirely until the account has had a second device, so
       single-machine users see zero footprint. -->
  <div v-if="hasOtherDevices" class="relative device-menu">
    <!-- Ghost trigger, matching the profile picker: bordered+filled chips
         aren't Atelier chrome; the menu carries the affordance. -->
    <button
      data-tour="device-chip"
      class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
      @click="menuOpen = !menuOpen"
      :title="isRemote ? `On ${activeDeviceName}` : 'This computer'"
    >
      <span
        class="w-1.5 h-1.5 rounded-full flex-shrink-0"
        :class="statusDotClass"
      />
      <span class="max-w-[140px] truncate">{{ activeDeviceName }}</span>
      <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
      </svg>
    </button>

    <transition name="menu">
      <div
        v-if="menuOpen"
        class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu min-w-[320px] overflow-hidden"
      >
        <div class="py-1">
          <DeviceRow
            label="This computer"
            :platform="null"
            :channel="selfChannel"
            :sandbox="selfSandbox"
            detail="always available"
            :selected="!isRemote"
            @select="pick(LOCAL_DEVICE)"
          />
          <DeviceRow
            v-for="device in devices"
            :key="device.deviceId"
            :label="device.name"
            :platform="device.platform"
            :channel="device.channel"
            :sandbox="device.sandbox"
            :detail="routeLabel(device)"
            :disabled="!device.serving"
            :selected="activeDeviceId === device.deviceId"
            @select="pick(device.deviceId)"
          />
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
  devices,
  hasOtherDevices,
  activeDeviceName,
  isRemote,
  connectionState,
  selfChannel,
  selfSandbox,
  routeLabel,
  switchToDevice,
  refresh,
} = useMultiDevice()

const menuOpen = ref(false)

// Status colours are status-only per the design language: blue-500 is never
// an interactive accent, so it is the right token for "connected".
const statusDotClass = computed(() => {
  if (connectionState.value === 'unreachable') return 'bg-red-500'
  if (connectionState.value === 'connecting') return 'bg-amber-500'
  return isRemote.value ? 'bg-blue-500' : 'bg-content-muted'
})

async function pick(deviceId) {
  menuOpen.value = false
  await switchToDevice(deviceId)
}

function onDocumentClick(event) {
  if (!event.target.closest('.device-menu')) menuOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  // Cheap and keeps "last seen" honest without a poller.
  void refresh()
})
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>
