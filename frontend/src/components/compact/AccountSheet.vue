<script setup lang="ts">
/**
 * The avatar sheet: the desktop sidebar footer and top-bar right side in one
 * place — account and balance, the server this window is on, profile,
 * background work, settings, feedback. Update pill and provider managers are
 * deliberately absent: those belong to the serving desktop's local island.
 */
import { computed } from 'vue'
import {
  ChatBubbleBottomCenterTextIcon, Cog6ToothIcon, CpuChipIcon, ServerStackIcon, UserCircleIcon, ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import Sheet from '../ui/Sheet.vue'
import { useAuth } from '../../composables/useAuth'
import { useCloudAccount } from '../../composables/useCloudAccount'
import { useMultiDevice } from '../../composables/useMultiDevice'
import { useProfile } from '../../composables/useProfile'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: []; openSettings: [section: string] }>()

const { isAuthenticated, user } = useAuth()
const { cloudUser, formatBalance, getPlanDisplayName } = useCloudAccount()
const { activeDeviceName } = useMultiDevice()
const { profiles, getCurrentProfile } = useProfile()

const accountEmail = computed(() => user.value?.email || '')
const accountBalance = computed(() => (cloudUser.value ? formatBalance(cloudUser.value.credits) : ''))
const planName = computed(() => (cloudUser.value ? getPlanDisplayName(cloudUser.value) : ''))
const profileName = computed(() => getCurrentProfile()?.name || '')
const hasProfiles = computed(() => profiles.value.length > 1)

const rows = computed(() => [
  { id: 'server', icon: ServerStackIcon, label: 'Server', detail: activeDeviceName.value, section: 'server' },
  ...(hasProfiles.value ? [{ id: 'profiles', icon: UserCircleIcon, label: 'Profile', detail: profileName.value, section: 'profiles' }] : []),
  { id: 'background', icon: CpuChipIcon, label: 'Background work', detail: '', section: 'background' },
  { id: 'settings', icon: Cog6ToothIcon, label: 'Settings', detail: '', section: 'folders' },
])

function open(section: string) {
  emit('openSettings', section)
}
</script>

<template>
  <Sheet :show="show" @close="emit('close')">
    <button
      type="button"
      class="w-full flex items-center gap-3 px-4 py-3 text-left border-none bg-transparent min-h-[64px]"
      @click="open('account')"
    >
      <span
        class="w-10 h-10 rounded-full flex-shrink-0 flex items-center justify-center text-sm font-semibold text-white"
        :class="isAuthenticated ? 'bg-gradient-to-br from-teal-600 via-cyan-500 to-indigo-500' : 'bg-overlay-light text-content-secondary'"
      >{{ isAuthenticated ? accountEmail.charAt(0).toUpperCase() : '' }}</span>
      <span class="flex-1 min-w-0">
        <span class="block truncate text-[15px] text-content">{{ isAuthenticated ? accountEmail : 'Stimma account' }}</span>
        <span class="block truncate text-xs text-content-tertiary">
          <template v-if="isAuthenticated">Stimma Cloud<template v-if="accountBalance"> · <span class="font-mono">{{ accountBalance }}</span></template><template v-if="planName"> · {{ planName }}</template></template>
          <template v-else>Sign in for cloud tools and sync</template>
        </span>
      </span>
      <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
    </button>

    <div class="divide-y divide-edge-subtle border-t border-edge-subtle">
      <button
        v-for="row in rows"
        :key="row.id"
        type="button"
        class="w-full flex items-center gap-3 px-4 min-h-[52px] text-left border-none bg-transparent"
        @click="open(row.section)"
      >
        <component :is="row.icon" class="w-6 h-6 text-content-secondary flex-shrink-0" />
        <span class="flex-1 min-w-0 truncate text-[15px] text-content">{{ row.label }}</span>
        <span v-if="row.detail" class="truncate max-w-[45%] text-xs font-mono text-content-tertiary">{{ row.detail }}</span>
        <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
      </button>
      <button
        type="button"
        class="w-full flex items-center gap-3 px-4 min-h-[52px] text-left border-none bg-transparent"
        @click="open('privacy')"
      >
        <ChatBubbleBottomCenterTextIcon class="w-6 h-6 text-content-secondary flex-shrink-0" />
        <span class="flex-1 min-w-0 truncate text-[15px] text-content">Send feedback</span>
        <ChevronRightIcon class="w-5 h-5 text-content-muted flex-shrink-0" />
      </button>
    </div>
  </Sheet>
</template>
