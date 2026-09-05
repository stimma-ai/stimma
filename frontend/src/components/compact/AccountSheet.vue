<script setup lang="ts">
/**
 * The avatar sheet: who you are and where you are. Account, the server
 * picker, the profile picker, Settings, Send feedback. Transient state
 * (background work) and provider managers live in the header's right side,
 * as they do on the desktop top bar, not here.
 */
import { computed, ref } from 'vue'
import {
  ChatBubbleBottomCenterTextIcon, Cog6ToothIcon, ServerStackIcon, UserCircleIcon, ChevronRightIcon,
  CheckIcon, LockClosedIcon, LockOpenIcon,
} from '@heroicons/vue/24/outline'
import Sheet from '../ui/Sheet.vue'
import { useAuth } from '../../composables/useAuth'
import { useCloudAccount } from '../../composables/useCloudAccount'
import { useMultiDevice, THIS_MACHINE_LABEL } from '../../composables/useMultiDevice'
import { useProfile, openProfileWindow } from '../../composables/useProfile'
import { getSavedRouteForProfile } from '../../composables/useRouteRestore'
import { clearCachedPin, hasCachedPin } from '../../composables/usePinLock'
import { useFeedback } from '../../composables/useFeedback'
import { usePrivacyLockdown } from '../../composables/usePrivacyLockdown'
import { useTelemetry } from '../../composables/useTelemetry'
import { isDesktop } from '../../desktop'
import { isOfficialBuild } from '../../distribution'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: []; openSettings: [section: string] }>()

const { isAuthenticated, user } = useAuth()
const { cloudUser, formatBalance, getPlanDisplayName } = useCloudAccount()
const md = useMultiDevice()
const { profiles, currentProfileId, setCurrentProfileId, getCurrentProfile } = useProfile()
const { openMenuFeedback } = useFeedback()
const { privacyLockdownActive } = usePrivacyLockdown()
const { track } = useTelemetry()

const accountEmail = computed(() => user.value?.email || '')
const accountBalance = computed(() => (cloudUser.value ? formatBalance(cloudUser.value.credits) : ''))
const planName = computed(() => (cloudUser.value ? getPlanDisplayName(cloudUser.value) : ''))
const profileName = computed(() => getCurrentProfile()?.name || '')
const canSendFeedback = computed(() => isOfficialBuild() && !privacyLockdownActive.value)

const serverOpen = ref(false)
const profileOpen = ref(false)

const serverDot = computed(() => {
  if (md.connectionState.value !== 'ready') return 'bg-red-500'
  return md.isRemote.value ? 'bg-blue-500' : 'bg-accent-hi'
})

function open(section: string) {
  emit('close')
  emit('openSettings', section)
}

async function pickServer(deviceId: string) {
  serverOpen.value = false
  emit('close')
  if (deviceId === md.LOCAL_DEVICE) await md.useLocalServer()
  else await md.switchToDevice(deviceId)
}

async function pickProfile(profileId: string) {
  profileOpen.value = false
  emit('close')
  if (profileId === currentProfileId.value) return
  track('profile_switched', {}, 'settings')
  if (await openProfileWindow(profileId)) return
  const targetRoute = getSavedRouteForProfile(profileId)
  setCurrentProfileId(profileId)
  window.location.href = targetRoute
}

function lockProfile(profileId: string) {
  track('profile_locked', {}, 'settings')
  clearCachedPin(profileId)
  profileOpen.value = false
  emit('close')
  if (profileId === currentProfileId.value) window.location.reload()
}

function sendFeedback() {
  emit('close')
  openMenuFeedback('menu')
}
</script>

<template>
  <Sheet :show="show" @close="emit('close')">
    <button
      type="button"
      class="sheet-row !min-h-[60px] py-2"
      @click="open('account')"
    >
      <span
        class="w-10 h-10 rounded-full flex-shrink-0 flex items-center justify-center text-sm font-semibold text-white"
        :class="isAuthenticated ? 'bg-gradient-to-br from-teal-600 via-cyan-500 to-indigo-500' : 'bg-overlay-light text-content-secondary'"
      >{{ isAuthenticated ? accountEmail.charAt(0).toUpperCase() : '' }}</span>
      <span class="flex-1 min-w-0">
        <span class="block truncate text-content">{{ isAuthenticated ? accountEmail : 'Stimma account' }}</span>
        <span class="block truncate text-xs text-content-tertiary">
          <template v-if="isAuthenticated">Stimma Cloud<template v-if="accountBalance"> · <span class="font-mono">{{ accountBalance }}</span></template><template v-if="planName"> · {{ planName }}</template></template>
          <template v-else>Sign in for cloud tools and sync</template>
        </span>
      </span>
      <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
    </button>

    <div class="divide-y divide-edge-subtle border-t border-edge-subtle">
      <!-- Server picker -->
      <button type="button" class="sheet-row" @click="serverOpen = true">
        <span class="relative flex-shrink-0">
          <ServerStackIcon class="sheet-row-icon" />
          <span class="absolute -right-0.5 -bottom-0.5 w-2 h-2 rounded-full ring-2 ring-surface" :class="serverDot"></span>
        </span>
        <span class="flex-1 min-w-0 truncate text-content">Server</span>
        <span class="sheet-row-detail">{{ md.activeDeviceName.value }}</span>
        <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
      </button>
      <!-- Profile picker -->
      <button type="button" class="sheet-row" @click="profileOpen = true">
        <UserCircleIcon class="sheet-row-icon" />
        <span class="flex-1 min-w-0 truncate text-content">Profile</span>
        <span class="sheet-row-detail">{{ profileName }}</span>
        <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
      </button>
      <button type="button" class="sheet-row" @click="open('')">
        <Cog6ToothIcon class="sheet-row-icon" />
        <span class="flex-1 min-w-0 truncate text-content">Settings</span>
        <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
      </button>
      <button v-if="canSendFeedback" type="button" class="sheet-row" @click="sendFeedback">
        <ChatBubbleBottomCenterTextIcon class="sheet-row-icon" />
        <span class="flex-1 min-w-0 truncate text-content">Send feedback</span>
      </button>
    </div>
  </Sheet>

  <!-- Server picker. On the desktop app the window can move between servers.
       In a phone browser the page IS the server it came from: show it, and
       point at settings for the rest. -->
  <Sheet :show="serverOpen" title="Server" @close="serverOpen = false">
    <div class="pb-2">
      <template v-if="isDesktop()">
        <button type="button" class="sheet-row" @click="pickServer(md.LOCAL_DEVICE)">
          <span class="w-2 h-2 rounded-full flex-shrink-0" :class="md.selfServing.value ? 'bg-accent-hi' : 'bg-content-muted'"></span>
          <span class="flex-1 min-w-0">
            <span class="block truncate text-content">{{ THIS_MACHINE_LABEL }}</span>
            <span v-if="md.selfName.value" class="block truncate text-xs font-mono text-content-tertiary">{{ md.selfName.value }}</span>
          </span>
          <CheckIcon v-if="!md.isRemote.value" class="w-5 h-5 text-accent-hi flex-shrink-0" />
        </button>
        <button v-for="d in md.onlineDevices.value" :key="d.deviceId" type="button" class="sheet-row" @click="pickServer(d.deviceId)">
          <span class="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0"></span>
          <span class="flex-1 min-w-0">
            <span class="block truncate text-content">{{ d.name }}</span>
            <span class="block truncate text-xs text-content-tertiary">Online</span>
          </span>
          <CheckIcon v-if="md.activeDeviceId.value === d.deviceId" class="w-5 h-5 text-accent-hi flex-shrink-0" />
        </button>
        <button v-for="d in md.offlineDevices.value" :key="d.deviceId" type="button" class="sheet-row opacity-60" @click="pickServer(d.deviceId)">
          <span class="w-2 h-2 rounded-full bg-content-muted flex-shrink-0"></span>
          <span class="flex-1 min-w-0">
            <span class="block truncate text-content">{{ d.name }}</span>
            <span class="block truncate text-xs text-content-tertiary">Last seen {{ md.lastSeenLabel(d) }}</span>
          </span>
          <CheckIcon v-if="md.activeDeviceId.value === d.deviceId" class="w-5 h-5 text-accent-hi flex-shrink-0" />
        </button>
      </template>
      <div v-else class="sheet-row">
        <span class="w-2 h-2 rounded-full flex-shrink-0" :class="serverDot"></span>
        <span class="flex-1 min-w-0">
          <span class="block truncate text-content">{{ md.activeDeviceName.value }}</span>
          <span class="block truncate text-xs text-content-tertiary">This browser is connected here</span>
        </span>
        <CheckIcon class="w-5 h-5 text-accent-hi flex-shrink-0" />
      </div>
      <div class="mt-2 border-t border-edge-subtle">
        <button type="button" class="sheet-row" @click="serverOpen = false; open('server')">
          <Cog6ToothIcon class="sheet-row-icon" />
          <span class="flex-1 min-w-0 truncate text-content">Server settings</span>
          <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
        </button>
      </div>
    </div>
  </Sheet>

  <!-- Profile picker -->
  <Sheet :show="profileOpen" title="Profile" @close="profileOpen = false">
    <div class="pb-2">
      <div v-for="p in profiles" :key="p.id" class="sheet-row !px-2">
        <button type="button" class="flex-1 min-w-0 flex items-center gap-3 min-h-[44px] px-2 text-left border-none bg-transparent" @click="pickProfile(p.id)">
          <span class="w-5 flex-shrink-0 flex items-center justify-center">
            <CheckIcon v-if="p.id === currentProfileId" class="w-5 h-5 text-accent-hi" />
          </span>
          <span class="flex-1 truncate text-content">{{ p.name }}</span>
        </button>
        <button
          v-if="p.has_pin && hasCachedPin(p.id)"
          type="button"
          class="w-11 h-11 flex items-center justify-center rounded-md border-none bg-transparent text-blue-500"
          aria-label="Lock profile"
          @click="lockProfile(p.id)"
        >
          <LockOpenIcon class="w-5 h-5" />
        </button>
        <span v-else-if="p.has_pin" class="w-11 h-11 flex items-center justify-center text-content-muted">
          <LockClosedIcon class="w-5 h-5" />
        </span>
      </div>
      <div class="mt-2 border-t border-edge-subtle">
        <button type="button" class="sheet-row" @click="profileOpen = false; open('profiles')">
          <Cog6ToothIcon class="sheet-row-icon" />
          <span class="flex-1 min-w-0 truncate text-content">Manage profiles</span>
          <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
        </button>
      </div>
    </div>
  </Sheet>
</template>

