<template>
  <div>
    <!-- Not signed in state -->
    <div v-if="privacyLockdownActive" class="min-h-[60vh] flex flex-col items-center justify-center text-center">
      <div class="w-16 h-16 mb-5 rounded-full bg-surface-raised border border-edge flex items-center justify-center">
        <svg class="w-8 h-8 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
        </svg>
      </div>
      <h3 class="text-lg font-semibold text-content mb-2">Privacy Lockdown</h3>
      <p class="text-sm text-content-tertiary">
        Sign-in to your account is disabled.
      </p>
    </div>

    <div v-else-if="!user" class="min-h-[60vh] flex items-start justify-center pt-10">
      <div class="w-full max-w-[640px] text-center">
        <img src="/logo.png" alt="" aria-hidden="true" class="mx-auto mb-7 h-[72px] w-[72px]" />
        <h3 class="text-[26px] font-semibold tracking-tight text-content">Sign in to Stimma</h3>
        <p class="mx-auto mt-2.5 mb-14 max-w-[420px] text-sm leading-6 text-content-secondary">
          Stimma doesn’t require an account — sign in when you want it connected.
        </p>

        <div class="mb-16 grid grid-cols-3 gap-10 text-center">
          <div>
            <div class="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-teal-600/10 via-cyan-500/10 to-indigo-500/10">
              <svg class="h-5 w-5 text-content-secondary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            </div>
            <h4 class="text-sm font-semibold text-content">Use hosted AI</h4>
            <p class="mt-1.5 text-[13px] leading-[1.55] text-content-tertiary">
              LLMs and 50+ image, video, and audio tools from many providers — pay with credits.
            </p>
          </div>

          <div>
            <div class="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-teal-600/10 via-cyan-500/10 to-indigo-500/10">
              <svg class="h-5 w-5 text-content-secondary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
              </svg>
            </div>
            <h4 class="text-sm font-semibold text-content">Share your work</h4>
            <p class="mt-1.5 text-[13px] leading-[1.55] text-content-tertiary">
              Publish the pieces you choose and share them with anyone, anywhere.
            </p>
          </div>

          <div>
            <div class="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-gradient-to-br from-teal-600/10 via-cyan-500/10 to-indigo-500/10">
              <svg class="h-5 w-5 text-content-secondary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
              </svg>
            </div>
            <h4 class="text-sm font-semibold text-content">Publish stimpacks</h4>
            <p class="mt-1.5 text-[13px] leading-[1.55] text-content-tertiary">
              Ship your own stimpacks for other Stimma users to discover and install.
            </p>
          </div>
        </div>

        <button
          @click="handleConnect"
          class="rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-8 py-2.5 text-sm font-semibold text-white transition-all hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 disabled:cursor-wait disabled:opacity-60"
          :disabled="isConnecting"
        >
          {{ isConnecting ? 'Connecting...' : 'Sign in to Stimma' }}
        </button>
        <p class="mt-4 text-[12.5px] text-content-muted">Free to create an account · No card required</p>

        <div class="mt-5 text-center"><RedeemCodeLink /></div>

        <p v-if="connectMessage" class="mt-4 text-center text-sm text-red-500">{{ connectMessage }}</p>
      </div>
    </div>

    <!-- Signed in state -->
    <div v-else class="max-w-[680px]">
      <header class="flex items-center gap-4">
        <img src="/logo.png" alt="" aria-hidden="true" class="h-12 w-12 shrink-0" />
        <div class="min-w-0">
          <h2 class="text-[22px] font-semibold tracking-tight text-content">Stimma Account</h2>
          <p class="mt-0.5 truncate text-[13.5px] text-content-tertiary">{{ user.email }}</p>
        </div>
        <div class="ml-auto flex shrink-0 items-center gap-4 text-[13.5px]">
          <button
            @click="openDashboard"
            class="font-medium text-accent transition-colors hover:text-accent/90"
          >
            Open dashboard
          </button>
          <button
            @click="handleSignOut"
            class="text-content-tertiary transition-colors hover:text-content"
          >
            Sign out
          </button>
        </div>
      </header>

      <!-- Balance card with gradient whisper border -->
      <div class="mt-10 rounded-[14px] p-[1px] bg-gradient-to-r from-teal-600/35 via-cyan-500/20 to-indigo-500/35">
        <div class="flex items-center gap-7 rounded-[13px] bg-surface px-[30px] py-7">
          <div class="shrink-0">
            <div class="stimma-cloud-text mb-1.5 text-[11px] font-semibold uppercase tracking-[0.1em]">Credits</div>
            <div v-if="isFirstLoad" class="h-10 w-32 animate-pulse rounded bg-white/10"></div>
            <div v-else-if="cloudError && !cloudUser" class="text-[40px] font-semibold leading-[1.05] tracking-tight text-content-muted">—</div>
            <div v-else class="text-[40px] font-semibold leading-[1.05] tracking-tight text-content">
              {{ formatBalance(cloudUser?.credits) }}
            </div>
          </div>
          <p class="ml-auto max-w-[300px] text-[13px] leading-5 text-content-tertiary">
            Use your credits for hosted image and video generation and LLM services.
          </p>
          <div v-if="isFirstLoad" class="h-9 w-28 shrink-0 animate-pulse rounded-lg bg-white/10"></div>
          <button
            v-else-if="!cloudError || cloudUser"
            @click="addBalance"
            class="shrink-0 rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-6 py-2.5 text-[13.5px] font-semibold text-white transition-all hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400"
          >
            Add credits
          </button>
        </div>
      </div>

      <RedeemCodeLink class="mt-3.5" />

      <!-- Error banner when cloud is unreachable -->
      <div v-if="cloudError && !isCloudLoading" class="mt-5 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3">
        <div class="flex items-center gap-2.5 min-w-0">
          <svg class="w-4 h-4 text-red-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
          <span class="text-sm text-red-400 truncate">{{ cloudErrorMessage }}</span>
        </div>
        <button
          @click="refreshAccount"
          class="flex-shrink-0 text-xs font-medium text-red-400 hover:text-red-300 border border-red-500/40 hover:border-red-400/60 rounded-md px-2.5 py-1 transition-colors"
        >
          Retry
        </button>
      </div>

      <section class="mt-9">
        <h3 class="text-sm font-semibold text-content">Account details</h3>
        <dl class="mt-4 grid grid-cols-2 gap-x-10 gap-y-6">
          <div class="min-w-0">
            <dt class="text-xs text-content-tertiary">Email</dt>
            <dd class="mt-1 truncate text-sm text-content">{{ user.email }}</dd>
          </div>
          <div>
            <dt class="text-xs text-content-tertiary">Member since</dt>
            <dd class="mt-1">
              <div v-if="isFirstLoad" class="h-4 w-28 animate-pulse rounded bg-white/10"></div>
              <div v-else-if="cloudUser?.createdAt" class="text-sm text-content">{{ formatDate(cloudUser.createdAt) }}</div>
              <div v-else class="text-sm text-content-muted">—</div>
            </dd>
          </div>
        </dl>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAuth } from '../../../composables/useAuth'
import { useCloudAccount } from '../../../composables/useCloudAccount'
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'
import { isTauri } from '../../../apiConfig'
import RedeemCodeLink from '../../RedeemCodeLink.vue'

defineProps({
  toolProviders: { type: Array, default: () => [] },
})

defineEmits(['close', 'navigate'])

const { user, authError, signOut, signInWithBrowser } = useAuth()
const { cloudBaseUrl, cloudUser, isCloudLoading, cloudError, fetchCloudAccount, ensureCloudBaseUrl, formatBalance } = useCloudAccount()
const { privacyLockdownActive } = usePrivacyLockdown()

const isConnecting = ref(false)
const connectError = ref('')

// First load = fetching with no data yet. Drives skeletons so the layout
// is fully reserved and nothing reflows when data lands. Once cloudUser is
// cached (module-scoped), reopening settings skips skeletons entirely.
const isFirstLoad = computed(() => isCloudLoading.value && !cloudUser.value)

const connectMessage = computed(() => connectError.value || authError.value || '')

const cloudErrorMessage = computed(() => {
  return cloudError.value?.message || "Couldn't load account info."
})

onMounted(async () => {
  await ensureCloudBaseUrl()
  if (user.value) {
    fetchCloudAccount()
  }
})

// When user signs in, fetch cloud account data
watch(user, async (newUser) => {
  if (newUser) {
    await ensureCloudBaseUrl()
    fetchCloudAccount()
  }
})

async function refreshAccount() {
  if (!isCloudLoading.value) {
    await fetchCloudAccount()
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

async function handleConnect() {
  isConnecting.value = true
  connectError.value = ''
  try {
    await signInWithBrowser()
  } catch (error) {
    connectError.value = error.message || 'Connection failed'
  } finally {
    isConnecting.value = false
  }
}

async function openDashboard() {
  const dashboardUrl = cloudBaseUrl.value + '/link/dashboard'
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(dashboardUrl)
  } else {
    window.open(dashboardUrl, '_blank')
  }
}

async function addBalance() {
  const addBalanceUrl = cloudBaseUrl.value + '/link/addcredits'

  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(addBalanceUrl)
  } else {
    window.open(addBalanceUrl, '_blank')
  }
}

async function handleSignOut() {
  await signOut()
}
</script>
