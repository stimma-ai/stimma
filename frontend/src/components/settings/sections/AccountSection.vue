<template>
  <div>
    <!-- Not signed in state -->
    <div v-if="!user" class="min-h-[60vh] flex flex-col items-center justify-center text-center">
      <div class="w-16 h-16 mb-5 rounded-full bg-gradient-to-br from-teal-600 via-cyan-500 to-indigo-500 flex items-center justify-center">
        <svg class="w-8 h-8 text-content" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
        </svg>
      </div>
      <h3 class="text-lg font-semibold text-content mb-2">Run the best AI models without GPU limits</h3>
      <p class="text-sm text-content-tertiary mb-6">
        Offload demanding jobs to the cloud. More power, less waiting.
      </p>
      <div class="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs text-content-secondary mb-6">
        <span class="flex items-center gap-1.5">
          <svg class="w-3 h-3 text-cyan-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
          Premium models
        </span>
        <span class="flex items-center gap-1.5">
          <svg class="w-3 h-3 text-cyan-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
          Faster processing
        </span>
        <span class="flex items-center gap-1.5">
          <svg class="w-3 h-3 text-cyan-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
          No GPU constraints
        </span>
        <span class="flex items-center gap-1.5">
          <svg class="w-3 h-3 text-cyan-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
          Hosted LLMs
        </span>
      </div>
      <button
        @click="handleConnect"
        class="px-6 py-2.5 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 text-white rounded-lg font-medium text-sm transition-all hover:shadow-lg hover:shadow-cyan-500/25 hover:-translate-y-0.5"
        :disabled="isConnecting"
      >
        {{ isConnecting ? 'Connecting...' : 'Unlock Stimma Cloud' }}
      </button>
      <p class="text-xs text-content-muted mt-2.5">No setup required</p>
      <p v-if="connectMessage" class="text-sm text-red-500 text-center mt-4">{{ connectMessage }}</p>
    </div>

    <!-- Signed in state - separate cards -->
    <div v-else class="space-y-4">
      <!-- Header Card -->
      <div class="relative rounded-xl p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
        <div class="rounded-xl bg-surface-overlay p-5">
          <div class="flex items-start justify-between">
            <div>
              <h2 class="text-xl font-semibold text-content mb-1">{{ greeting }}, {{ userName }}!</h2>
              <p class="text-sm text-content-tertiary">Here's an overview of your Stimma account.</p>
            </div>
            <!-- 3-dot menu -->
            <div class="relative">
              <button
                @click="showMenu = !showMenu"
                class="p-1.5 rounded-lg text-content-tertiary hover:text-content hover:bg-surface-raised/50 transition-colors"
              >
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
                </svg>
              </button>
              <!-- Backdrop to close menu -->
              <div v-if="showMenu" class="fixed inset-0 z-10" @click="showMenu = false"></div>
              <div
                v-if="showMenu"
                class="absolute right-0 mt-1 w-48 rounded-lg bg-surface border border-edge shadow-xl py-1 z-20"
              >
                <button
                  @click="openDashboard(); showMenu = false"
                  class="w-full px-4 py-2 text-left text-sm text-content hover:bg-surface-raised/50 flex items-center gap-2"
                >
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                  Go to Dashboard
                </button>
                <button
                  @click="handleSignOut"
                  class="w-full px-4 py-2 text-left text-sm text-content hover:bg-surface-raised/50 flex items-center gap-2"
                >
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9" />
                  </svg>
                  Sign Out
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Error banner when cloud is unreachable -->
      <div v-if="cloudError && !isCloudLoading" class="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 flex items-center justify-between gap-3">
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

      <!-- Credits Card -->
      <div class="relative rounded-xl p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
        <div class="rounded-xl bg-surface-overlay p-5">
          <div class="text-sm font-semibold text-content mb-3">Balance</div>
          <div class="flex items-end justify-between">
            <button
              @click="refreshAccount"
              class="text-left hover:opacity-80 transition-opacity"
              :class="{ 'cursor-wait': isCloudLoading }"
              title="Click to refresh"
            >
              <div v-if="isCloudLoading" class="flex items-baseline gap-2">
                <span class="text-3xl font-bold text-content-muted animate-pulse">---</span>
              </div>
              <div v-else-if="cloudError && !cloudUser" class="flex items-baseline gap-2">
                <span class="text-3xl font-bold text-content-muted">—</span>
              </div>
              <div v-else class="flex items-baseline gap-2">
                <span class="text-3xl font-bold bg-gradient-to-r from-teal-600 to-indigo-600 dark:from-cyan-400 dark:to-indigo-400 bg-clip-text text-transparent">
                  {{ formatBalance(cloudUser?.credits) }}
                </span>
              </div>
            </button>
            <!-- Show add credits for paid tiers, CTA for free tier -->
            <button
              v-if="hasPaidSubscription"
              @click="addBalance"
              class="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-white rounded-lg text-sm font-medium transition-colors"
            >
              Add Balance
            </button>
            <button
              v-else-if="!cloudError || cloudUser"
              @click="openGetStarted"
              class="px-4 py-2 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-white rounded-lg text-sm font-medium transition-all"
            >
              Get Started
            </button>
          </div>
          <p v-if="!hasPaidSubscription && (!cloudError || cloudUser)" class="text-sm text-content-muted mt-3">
            Subscribe to Stimma Cloud for hosted image and video generation, or configure your own providers.
          </p>
        </div>
      </div>

      <!-- Usage Card - show for paid tiers -->
      <div v-if="hasPaidSubscription" class="relative rounded-xl p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
        <div class="rounded-xl bg-surface-overlay p-5">
          <div class="text-sm font-semibold text-content mb-4">Usage</div>

          <div class="grid grid-cols-2 gap-5">
            <!-- Session window -->
            <div class="flex flex-col gap-2">
              <div class="flex items-baseline justify-between">
                <span class="text-[11px] font-semibold text-black/40 dark:text-white/50 uppercase tracking-wider">Session</span>
                <span v-if="cloudUser?.usageWindows?.session" class="text-lg font-semibold text-content">{{ cloudUser.usageWindows.session.percentUsed }}%</span>
                <span v-else class="text-sm text-black/30 dark:text-white/30">Idle</span>
              </div>
              <div class="h-1 bg-black/10 dark:bg-white/10 rounded-full overflow-hidden">
                <div
                  v-if="cloudUser?.usageWindows?.session"
                  class="h-full rounded-full transition-all duration-300"
                  :class="cloudUser.usageWindows.session.percentUsed > 95 ? 'bg-red-500' : cloudUser.usageWindows.session.percentUsed > 80 ? 'bg-amber-500' : 'bg-gradient-to-r from-teal-500 to-emerald-500'"
                  :style="{ width: cloudUser.usageWindows.session.percentUsed + '%' }"
                ></div>
              </div>
              <span v-if="cloudUser?.usageWindows?.session" class="text-[11px] text-black/40 dark:text-white/40">Resets {{ formatDate(cloudUser.usageWindows.session.resetsAt) }}</span>
              <span v-else class="text-[11px] text-black/30 dark:text-white/30">Starts on next request</span>
            </div>

            <!-- Weekly window -->
            <div class="flex flex-col gap-2">
              <div class="flex items-baseline justify-between">
                <span class="text-[11px] font-semibold text-black/40 dark:text-white/50 uppercase tracking-wider">Week</span>
                <span v-if="cloudUser?.usageWindows?.weekly" class="text-lg font-semibold text-content">{{ cloudUser.usageWindows.weekly.percentUsed }}%</span>
                <span v-else class="text-sm text-black/30 dark:text-white/30">Idle</span>
              </div>
              <div class="h-1 bg-black/10 dark:bg-white/10 rounded-full overflow-hidden">
                <div
                  v-if="cloudUser?.usageWindows?.weekly"
                  class="h-full rounded-full transition-all duration-300"
                  :class="cloudUser.usageWindows.weekly.percentUsed > 95 ? 'bg-red-500' : cloudUser.usageWindows.weekly.percentUsed > 80 ? 'bg-amber-500' : 'bg-gradient-to-r from-teal-500 to-emerald-500'"
                  :style="{ width: cloudUser.usageWindows.weekly.percentUsed + '%' }"
                ></div>
              </div>
              <span v-if="cloudUser?.usageWindows?.weekly" class="text-[11px] text-black/40 dark:text-white/40">Resets {{ formatDate(cloudUser.usageWindows.weekly.resetsAt) }}</span>
              <span v-else class="text-[11px] text-black/30 dark:text-white/30">Starts on next request</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Account Details Card -->
      <div class="relative rounded-xl p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
        <div class="rounded-xl bg-surface-overlay p-5">
          <div class="text-sm font-semibold text-content mb-4">Account</div>
          <div class="grid grid-cols-3 gap-6">
            <div>
              <div class="text-xs text-content-muted mb-1">Email</div>
              <button @click="openDashboard" class="text-sm text-content truncate hover:text-content-secondary transition-colors text-left">{{ user.email }}</button>
            </div>
            <div>
              <div class="text-xs text-content-muted mb-1">Plan</div>
              <div class="flex items-center gap-2">
                <span
                  v-if="cloudUser"
                  class="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium"
                  :class="getPlanBadgeClass(cloudUser.tier)"
                >
                  {{ getPlanDisplayName(cloudUser) }}
                </span>
                <button
                  v-if="cloudUser && !hasPaidSubscription"
                  @click="openGetStarted"
                  class="text-xs text-indigo-600 hover:text-indigo-500 dark:text-indigo-400 dark:hover:text-indigo-300 transition-colors"
                >
                  Upgrade
                </button>
                <span v-if="!cloudUser" class="text-sm text-content-muted">—</span>
              </div>
            </div>
            <div>
              <div class="text-xs text-content-muted mb-1">Member Since</div>
              <div v-if="cloudUser?.createdAt" class="text-sm text-content">{{ formatDate(cloudUser.createdAt) }}</div>
              <div v-else class="text-sm text-content-muted">—</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAuth } from '../../../composables/useAuth'
import { useCloudAccount } from '../../../composables/useCloudAccount'
import { isTauri } from '../../../apiConfig'

const emit = defineEmits(['close'])

const { user, authError, signOut, signInWithBrowser } = useAuth()
const { cloudBaseUrl, cloudUser, isCloudLoading, cloudError, fetchCloudAccount, ensureCloudBaseUrl, formatBalance, getPlanDisplayName } = useCloudAccount()

const showMenu = ref(false)
const isConnecting = ref(false)
const connectError = ref('')

// Check if user has a paid subscription (not free tier)
const hasPaidSubscription = computed(() => {
  if (!cloudUser.value) return false
  const tier = (cloudUser.value.tier || '').toLowerCase()
  return tier && tier !== 'free' && tier !== 'byoai'
})

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
})

const userName = computed(() => {
  if (!user.value) return ''
  // Try displayName, then name, then email prefix
  if (user.value.displayName) return user.value.displayName.split(' ')[0]
  if (user.value.name) return user.value.name.split(' ')[0]
  if (user.value.email) return user.value.email.split('@')[0]
  return 'there'
})

const connectMessage = computed(() => connectError.value || authError.value || '')

const cloudErrorMessage = computed(() => {
  return cloudError.value?.message || "Couldn't load Stimma Cloud account info."
})

onMounted(async () => {
  await ensureCloudBaseUrl()
  if (user.value) {
    fetchCloudAccount()
  }
})

// When user signs in (e.g. via "Get Stimma Cloud"), fetch cloud account data
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

function formatNumber(num) {
  if (num == null) return '0'
  return num.toLocaleString()
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function getPlanBadgeClass(tier) {
  const tierLower = (tier || '').toLowerCase()
  if (tierLower === 'power') return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-400'
  if (tierLower === 'creator') return 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/50 dark:text-cyan-400'
  if (tierLower === 'maker') return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400'
  return 'bg-surface-raised/50 text-content-tertiary'
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

async function openGetStarted() {
  const getStartedUrl = cloudBaseUrl.value + '/link/getstarted'
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(getStartedUrl)
  } else {
    window.open(getStartedUrl, '_blank')
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
