<template>
  <!-- Hidden entirely until the account has offered a second server, so
       single-machine users see zero footprint. Note this does NOT depend on
       whether THIS install serves: pointing a laptop at the studio machine
       must not require offering the laptop in return.

       Two triggers, one menu. `footer` is the everyday home: a 32px icon in
       the sidebar footer strip beside feedback and settings, because picking
       a server is rare and belongs with the other occasional actions, and
       because it leaves the account chip's name and balance untouched. The
       presence dot on its corner carries the state you actually need at a
       glance; the name lives in the tooltip and the menu. `chip` (name +
       dot) survives for the connection screen, which has no sidebar. -->
  <div v-if="hasOtherDevices" class="device-menu" :class="isFooter ? 'contents' : 'relative'">
    <button
      v-if="isFooter"
      data-tour="device-chip"
      class="relative w-8 h-8 flex-shrink-0 flex items-center justify-center rounded text-content-tertiary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle border-none bg-transparent"
      :class="menuOpen ? 'text-content bg-overlay-subtle' : ''"
      :title="isRemote ? `Server: ${activeDeviceName}` : 'Server: this install'"
      @click="toggleMenu"
    >
      <svg class="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 12V5.25" />
      </svg>
      <!-- Presence dot rides the icon's corner; ringed in surface so it reads
           as a badge rather than part of the glyph. -->
      <span
        class="absolute right-1 bottom-1 w-2 h-2 rounded-full ring-2 ring-surface"
        :class="statusDotClass"
      />
    </button>

    <!-- Ghost trigger, matching the profile picker: bordered+filled chips
         aren't Atelier chrome; the menu carries the affordance. -->
    <button
      v-else
      data-tour="device-chip"
      class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
      @click="toggleMenu"
      :title="isRemote ? `On ${activeDeviceName}` : 'Local server'"
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
      <!-- Footer: opens upward and spans the footer's width. A 300px panel
           hanging off a 32px icon at the sidebar's right edge would clip
           against the window, so the panel anchors to the footer container
           (the `contents` wrapper makes that the positioning parent). -->
      <div
        v-if="menuOpen"
        class="absolute bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu overflow-hidden"
        :class="isFooter
          ? 'bottom-[calc(100%+0.375rem)] left-2 right-2 origin-bottom'
          : 'top-[calc(100%+0.5rem)] right-0 min-w-[300px]'"
      >
        <div class="py-1">
          <DeviceRow
            :label="selfName || 'Local server'"
            :channel="selfChannel"
            :sandbox="selfSandbox"
            :detail="selfName ? 'local' : ''"
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
             server vanishing from the menu is worse than a quiet count. -->
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

const props = defineProps({
  /** `footer`: sidebar-footer icon with a presence dot, menu opens upward.
   *  `chip`: name + dot for surfaces without a sidebar (connection screen). */
  variant: { type: String, default: 'chip' },
})
const isFooter = computed(() => props.variant === 'footer')

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
