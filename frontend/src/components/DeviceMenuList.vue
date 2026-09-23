<template>
  <!-- The one server list, shared by the sidebar-footer picker and the
       compact account sheet so the two entry points never drift. Rows are
       DeviceRow; the phone shells get two more, because on a phone the list
       is only half the story: the native connection screen (with the dev
       server panel) and "disconnect" are the actions people actually come
       here for, and the shell hides both behind the bridge. -->
  <div>
    <!-- The local row is named for the seat, never the hostname: "studio"
         in a list of servers reads as one more server to choose between.
         The hostname is the subtitle, where it answers "which one is
         this?" without competing with the answer to "where am I?". -->
    <div class="py-1">
      <DeviceRow
        v-if="!mobileShell"
        :label="THIS_MACHINE_LABEL"
        :detail="selfDetail"
        :channel="selfChannel"
        :sandbox="selfSandbox"
        :presence="selfServing ? 'serving' : 'idle'"
        :selected="!isRemote"
        :class="rowClass"
        @select="pick(LOCAL_DEVICE)"
      />
      <DeviceRow
        v-for="device in onlineDevices"
        :key="device.deviceId"
        :label="device.name"
        :detail="activeDeviceId === device.deviceId ? 'Connected' : 'Online'"
        :channel="device.channel"
        :sandbox="device.sandbox"
        presence="online"
        :selected="activeDeviceId === device.deviceId"
        :class="rowClass"
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
        :removable="!mobileShell"
        :selected="activeDeviceId === device.deviceId"
        :class="rowClass"
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
          <Button v-if="!mobileShell" size="sm" @click="openServerSettings">Serve from {{ THIS_MACHINE_LABEL }}</Button>
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

    <!-- Phone shell: the roster above is what the account offers, but the
         shell's own connection screen is where servers are chosen (and, in
         dev builds, where a dev server is entered), and leaving the current
         server is a shell action too. Both live here, on the picker, because
         this is where people look when they want to be somewhere else. -->
    <div v-if="mobileShell" class="border-t border-edge-subtle py-1">
      <button
        type="button"
        class="w-full flex items-center gap-2.5 px-3 text-left text-xs text-content transition-colors cursor-pointer hover:bg-overlay-subtle bg-transparent border-none"
        :class="rowClass"
        role="menuitem"
        :disabled="pending"
        @click="chooseAnotherServer"
      >
        <svg class="w-[17px] h-[17px] flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
        </svg>
        <span class="flex-1">Choose another server</span>
      </button>
      <button
        type="button"
        class="w-full flex items-center gap-2.5 px-3 text-left text-xs text-content transition-colors cursor-pointer hover:bg-overlay-subtle bg-transparent border-none"
        :class="rowClass"
        role="menuitem"
        :disabled="pending"
        @click="disconnect"
      >
        <svg class="w-[17px] h-[17px] flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.181 8.68a4.503 4.503 0 0 1 1.903 6.405m-9.768-2.782L3.56 14.06a4.5 4.5 0 0 0 6.364 6.365l3.129-3.129m5.614-5.615 1.757-1.757a4.5 4.5 0 0 0-6.364-6.365l-4.5 4.5c-.258.26-.479.541-.661.84m1.903 6.405a4.495 4.495 0 0 1-1.242-.88 4.483 4.483 0 0 1-1.062-1.683m6.587 2.345 5.907 5.907m-5.907-5.907L8.898 8.898M2.991 2.99 8.898 8.9" />
        </svg>
        <span class="flex-1">Disconnect from server</span>
      </button>
      <p v-if="error" class="px-3 pt-1 pb-2 text-[11px] text-content-secondary" role="alert">{{ error }}</p>
    </div>

    <!-- Keeps the settings block one click away after the empty state is
         gone; the menu is where people look when a server is missing. -->
    <div v-if="!(rosterLoaded && !devices.length)" class="border-t border-edge-subtle">
      <button
        class="w-full flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-content-tertiary transition-colors cursor-pointer hover:text-content-secondary hover:bg-overlay-subtle bg-transparent border-none coarse:min-h-[44px]"
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
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useMultiDevice, THIS_MACHINE_LABEL, SERVER_DOCS_URL } from '../composables/useMultiDevice'
import { desktop } from '../desktop'
import { disconnectMobileServer, showMobileConnections } from '../desktop/mobileBridge'
import DeviceRow from './DeviceRow.vue'
import Button from './ui/Button.vue'

/** Fired after any action that should close the menu or sheet holding the list. */
const emit = defineEmits(['done'])

const {
  LOCAL_DEVICE,
  activeDeviceId,
  devices,
  onlineDevices,
  offlineDevices,
  isRemote,
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

const mobileShell = ['ios', 'android'].includes(desktop.kind)
const pending = ref(false)
const error = ref('')

// Rows are menu-sized on a pointer; on touch they grow to the 44px target
// the kit uses everywhere else, without the list needing a second layout.
const rowClass = 'coarse:min-h-[44px] coarse:text-[13px]'

/** Hostname, and whether this install is offered, under the "This PC" row. */
const selfDetail = computed(() => {
  const name = selfName.value || ''
  if (!selfServing.value) return name
  return name ? `${name} · serving` : 'serving'
})

async function pick(deviceId) {
  emit('done')
  await switchToDevice(deviceId)
}

async function chooseAnotherServer() {
  await shellAction(() => showMobileConnections())
}

async function disconnect() {
  await shellAction(() => disconnectMobileServer())
}

async function shellAction(run) {
  if (pending.value) return
  pending.value = true
  error.value = ''
  try {
    await run()
    emit('done')
  } catch {
    error.value = 'Could not reach the phone shell. Please try again.'
  } finally {
    pending.value = false
  }
}

function openServerSettings() {
  emit('done')
  window.dispatchEvent(new CustomEvent('open-settings', { detail: 'server' }))
}

function openDocs() {
  void desktop.openExternal(SERVER_DOCS_URL)
}

// Presence can have moved since the list was last shown; re-read on mount
// rather than polling for a list nobody is looking at. Self too: serving
// may have been toggled in Settings since the last read.
onMounted(() => {
  void refresh()
  void loadSelf()
})
</script>
