<template>
  <!-- Always present once signed in. It used to hide until the account had a
       second server, but a control that appears out of nowhere the day a
       friend's machine shows up teaches nobody anything: with no other
       servers, the menu explains the feature and says where to turn it on.

       Two triggers, one menu. `footer` is the everyday home: a 32px icon in
       the sidebar footer strip beside feedback and settings, because picking
       a server is rare and belongs with the other occasional actions, and
       because it leaves the account chip's name and balance untouched. The
       presence dot on its corner carries the state you actually need at a
       glance; the name lives in the tooltip and the menu. `chip` (name +
       dot) survives for the connection screen, which has no sidebar. -->
  <div class="device-menu" :class="isFooter ? 'contents' : 'relative'">
    <!-- Same kit Tooltip as the feedback and settings buttons beside it, so
         the footer's hover behaviour is one thing, not two. -->
    <Tooltip v-if="isFooter" :text="`Server: ${activeLabel}`" class="w-8 flex-shrink-0">
      <button
        data-tour="device-chip"
        class="relative w-8 h-8 flex-shrink-0 flex items-center justify-center rounded text-content-tertiary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle border-none bg-transparent"
        :class="menuOpen ? 'text-content bg-overlay-subtle' : ''"
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
    </Tooltip>

    <!-- Ghost trigger, matching the profile picker: bordered+filled chips
         aren't Atelier chrome; the menu carries the affordance. -->
    <button
      v-else
      data-tour="device-chip"
      class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
      @click="toggleMenu"
      :title="`Server: ${activeLabel}`"
    >
      <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="statusDotClass" />
      <span class="max-w-[140px] truncate">{{ activeLabel }}</span>
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
        role="menu"
      >
        <!-- The local row is named for the seat, never the hostname: "studio"
             in a list of servers reads as one more server to choose between.
             The hostname is the subtitle, where it answers "which one is
             this?" without competing with the answer to "where am I?". -->
        <div class="py-1">
          <DeviceRow
            :label="THIS_MACHINE_LABEL"
            :detail="selfDetail"
            :channel="selfChannel"
            :sandbox="selfSandbox"
            :presence="selfServing ? 'serving' : 'idle'"
            :selected="!isRemote"
            @select="pick(LOCAL_DEVICE)"
          />
          <DeviceRow
            v-for="device in onlineDevices"
            :key="device.deviceId"
            :label="device.name"
            detail="Online"
            :channel="device.channel"
            :sandbox="device.sandbox"
            presence="online"
            :selected="activeDeviceId === device.deviceId"
            @select="pick(device.deviceId)"
          />
          <!-- Offered but not up. In the same list, dimmed, with a last-seen
               line — there are never many, and a server vanishing from the
               menu is worse than a quiet extra row. -->
          <DeviceRow
            v-for="device in offlineDevices"
            :key="device.deviceId"
            :label="device.name"
            :detail="`Last seen ${lastSeenLabel(device)}`"
            :channel="device.channel"
            :sandbox="device.sandbox"
            presence="offline"
            muted
            removable
            :selected="activeDeviceId === device.deviceId"
            @select="pick(device.deviceId)"
            @remove="forgetDevice(device.deviceId)"
          />
        </div>

        <!-- Nothing offered on the account yet. Two states, because the next
             step depends on whether THIS install is already serving: if not,
             the likely wish is "reach this machine from my laptop", so the
             primary action turns serving on here. If it is, the next step
             happens on the other machine, and there is nothing to press. -->
        <div v-if="rosterLoaded && !devices.length" class="border-t border-edge-subtle px-3.5 pt-3 pb-3">
          <template v-if="!selfServing">
            <div class="flex items-end gap-1.5 text-content-muted mb-2.5">
              <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 14.15V7.4a2.25 2.25 0 0 0-2.25-2.25H6A2.25 2.25 0 0 0 3.75 7.4v6.75m16.5 0h-16.5m16.5 0 1.05 2.45a1.5 1.5 0 0 1-1.38 2.09H3.83a1.5 1.5 0 0 1-1.38-2.09l1.05-2.45" />
              </svg>
              <svg class="w-4 h-4 mb-1 opacity-70" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
              </svg>
              <svg class="w-6 h-6 text-accent-hi" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25" />
              </svg>
            </div>
            <div class="font-brand font-semibold text-[13px] text-content">Your other servers appear here</div>
            <p class="mt-1 text-[11px] leading-relaxed text-content-tertiary">
              Turn on Stimma Server on any install signed in as you. Pick it here to work from its library and tools.
            </p>
            <ol class="mt-2 space-y-1.5 text-[11px] leading-relaxed text-content-tertiary">
              <li class="flex gap-2">
                <span class="flex-shrink-0 w-4 h-4 rounded-full bg-overlay-hover text-content-secondary text-[10px] flex items-center justify-center mt-px">1</span>
                <span>On the install you want to reach: <span class="text-content-secondary font-medium">Settings → Stimma Server</span>, turn on <span class="text-content-secondary font-medium">Enable server</span>.</span>
              </li>
              <li class="flex gap-2">
                <span class="flex-shrink-0 w-4 h-4 rounded-full bg-overlay-hover text-content-secondary text-[10px] flex items-center justify-center mt-px">2</span>
                <span>Sign in with the same account here.</span>
              </li>
            </ol>
            <div class="mt-3 flex items-center gap-2">
              <Button size="sm" @click="openServerSettings">Serve from {{ THIS_MACHINE_LABEL }}</Button>
              <Button size="sm" variant="ghost" @click="openDocs">Learn more ↗</Button>
            </div>
          </template>
          <template v-else>
            <div class="font-brand font-semibold text-[13px] text-content">No other servers yet</div>
            <p class="mt-1 text-[11px] leading-relaxed text-content-tertiary">
              {{ THIS_MACHINE_LABEL }} is serving as
              <span class="font-mono text-content-secondary">{{ selfName }}</span>.
              Sign in on another install and pick it from this menu there.
            </p>
            <p class="mt-1.5 text-[11px] leading-relaxed text-content-tertiary">
              To reach another server from here, turn on Stimma Server on it.
            </p>
            <div class="mt-3 flex items-center gap-2">
              <Button size="sm" variant="ghost" @click="openServerSettings">Server settings</Button>
              <Button size="sm" variant="ghost" @click="openDocs">Learn more ↗</Button>
            </div>
          </template>
        </div>

        <!-- Keeps the settings block one click away after the empty state is
             gone; the menu is where people look when a server is missing. -->
        <div v-else class="border-t border-edge-subtle">
          <button
            class="w-full flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-content-tertiary transition-colors cursor-pointer hover:text-content-secondary hover:bg-overlay-subtle bg-transparent border-none"
            @click="openServerSettings"
          >
            <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
            </svg>
            <span>Server settings</span>
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useMultiDevice, THIS_MACHINE_LABEL, SERVER_DOCS_URL } from '../composables/useMultiDevice'
import { desktop } from '../desktop'
import DeviceRow from './DeviceRow.vue'
import Button from './ui/Button.vue'
import Tooltip from './ui/Tooltip.vue'

const props = defineProps({
  /** `footer`: sidebar-footer icon with a presence dot, menu opens upward.
   *  `chip`: name + dot for surfaces without a sidebar (connection screen). */
  variant: { type: String, default: 'chip' },
})
const isFooter = computed(() => props.variant === 'footer')

const {
  LOCAL_DEVICE,
  activeDeviceId,
  devices,
  onlineDevices,
  offlineDevices,
  activeDeviceName,
  isRemote,
  connectionState,
  selfName,
  selfChannel,
  selfSandbox,
  selfServing,
  rosterLoaded,
  lastSeenLabel,
  switchToDevice,
  forgetDevice,
  refresh,
  loadSelf,
} = useMultiDevice()

const menuOpen = ref(false)

/** What the trigger calls the active server: a remote by name, the seat by role. */
const activeLabel = computed(() => (isRemote.value ? activeDeviceName.value : THIS_MACHINE_LABEL))

/** Hostname, and whether this install is offered, under the "This PC" row. */
const selfDetail = computed(() => {
  const name = selfName.value || ''
  if (!selfServing.value) return name
  return name ? `${name} · serving` : 'serving'
})

// Status colours are status-only per the design language: blue-500 is never
// an interactive accent, so it is the right token for "connected". Teal on
// the local dot means "this install is serving", which is the one fact worth
// showing without opening Settings.
const statusDotClass = computed(() => {
  if (connectionState.value === 'unreachable') return 'bg-red-500'
  if (connectionState.value === 'connecting') return 'bg-amber-500'
  if (isRemote.value) return 'bg-blue-500'
  return selfServing.value ? 'bg-accent-hi' : 'bg-content-muted'
})

function toggleMenu() {
  menuOpen.value = !menuOpen.value
  // Presence can have moved while the menu was shut; re-read on open rather
  // than polling for a menu nobody is looking at. Self too: serving may have
  // been toggled in Settings since the last read.
  if (menuOpen.value) {
    void refresh()
    void loadSelf()
  }
}

async function pick(deviceId) {
  menuOpen.value = false
  await switchToDevice(deviceId)
}

function openServerSettings() {
  menuOpen.value = false
  window.dispatchEvent(new CustomEvent('open-settings', { detail: 'server' }))
}

function openDocs() {
  void desktop.openExternal(SERVER_DOCS_URL)
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
