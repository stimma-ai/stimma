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
        Stimma Cloud sign-in is disabled.
      </p>
    </div>

    <div v-else-if="!user" class="min-h-[60vh] flex flex-col items-center justify-center text-center">
      <!-- Local tools connected: pitch cloud as an addition to a working stack -->
      <template v-if="hasLocalTools">
        <div class="flex items-center gap-2 text-xs text-content-tertiary bg-surface border border-edge rounded-full px-3.5 py-1.5 mb-5">
          <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
          Local tools connected
        </div>
        <h3 class="text-2xl font-semibold text-content mb-3 max-w-md text-balance">Add the frontier to your <span class="stimma-cloud-text">local stack.</span></h3>
        <p class="text-sm text-content-tertiary leading-relaxed max-w-md mb-6">
          Your local setup stays as it is. Stimma Cloud adds the newest closed image and video models, plus a hosted agent. Run each job wherever you choose.
        </p>
        <button
          @click="handleConnect"
          class="px-6 py-2.5 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 text-white rounded-lg font-medium text-sm transition-all hover:shadow-lg hover:shadow-cyan-500/25 hover:-translate-y-0.5"
          :disabled="isConnecting"
        >
          {{ isConnecting ? 'Connecting...' : 'Connect Stimma Cloud' }}
        </button>
        <p class="text-xs text-content-muted mt-2.5">Works alongside your local tools · Sign in or create an account in your browser</p>
      </template>

      <!-- Nothing connected: cloud is the missing piece, with local setup as the alternative -->
      <template v-else>
        <svg class="w-8 h-8 mb-4" viewBox="0 0 24 24" fill="none" stroke="url(#account-cloud-grad)" stroke-width="1.5" aria-hidden="true">
          <defs>
            <linearGradient id="account-cloud-grad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#0d9488" />
              <stop offset="0.5" stop-color="#06b6d4" />
              <stop offset="1" stop-color="#6366f1" />
            </linearGradient>
          </defs>
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
        </svg>
        <h3 class="text-2xl font-semibold text-content mb-3 max-w-md text-balance">Stimma isn't connected to any AI <span class="stimma-cloud-text">yet.</span></h3>
        <p class="text-sm text-content-tertiary leading-relaxed max-w-md mb-6">
          Stimma needs two things to work: tools that generate images and video, and a model that powers the agent. Stimma Cloud is both. Sign in once and start creating.
        </p>
        <button
          @click="handleConnect"
          class="px-6 py-2.5 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 text-white rounded-lg font-medium text-sm transition-all hover:shadow-lg hover:shadow-cyan-500/25 hover:-translate-y-0.5"
          :disabled="isConnecting"
        >
          {{ isConnecting ? 'Connecting...' : 'Connect Stimma Cloud' }}
        </button>
        <p class="text-xs text-content-muted mt-2.5">No setup required · Sign in or create an account in your browser</p>
        <div class="mt-8 pt-5 border-t border-edge w-full max-w-sm">
          <div class="text-[11px] font-semibold uppercase tracking-wider text-content-muted mb-2.5">Or, bring your own AI</div>
          <div class="flex flex-col items-center gap-1.5 text-xs">
            <button @click="emit('navigate', 'tools')" class="text-content-tertiary hover:text-content transition-colors">
              Connect generation tools →
            </button>
            <button @click="emit('navigate', 'ai-services')" class="text-content-tertiary hover:text-content transition-colors">
              Point the agent at a local LLM →
            </button>
          </div>
        </div>
      </template>
      <p v-if="connectMessage" class="text-sm text-red-500 text-center mt-4">{{ connectMessage }}</p>
    </div>

    <!-- Signed in state - separate cards -->
    <div v-else class="space-y-4">
      <!-- Hero card: greeting + balance. The single Stimma Cloud brand moment -->
      <div class="relative overflow-hidden rounded-xl border border-edge-strong bg-surface-raised p-5 bg-[radial-gradient(120%_140%_at_0%_0%,rgba(6,182,212,0.10),transparent_55%)]">
        <!-- Gradient accent rail -->
        <div class="absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-teal-600 via-cyan-500 to-indigo-500"></div>

        <!-- Greeting + 3-dot menu -->
        <div class="flex items-start justify-between">
          <div>
            <h2 class="text-xl font-semibold text-content mb-1">{{ greeting }}, {{ userName }}!</h2>
            <p class="text-sm text-content-tertiary">Here's an overview of your Stimma account.</p>
          </div>
          <div class="relative">
            <button
              @click="showMenu = !showMenu"
              class="p-1.5 rounded-lg text-content-tertiary hover:text-content hover:bg-surface-hover/60 transition-colors"
            >
              <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
              </svg>
            </button>
            <div v-if="showMenu" class="fixed inset-0 z-10" @click="showMenu = false"></div>
            <div
              v-if="showMenu"
              class="absolute right-0 mt-1 w-48 rounded-lg bg-surface border border-edge shadow-xl py-1 z-20"
            >
              <button
                @click="openDashboard(); showMenu = false"
                class="w-full px-4 py-2 text-left text-sm text-content hover:bg-surface-hover flex items-center gap-2"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                </svg>
                Go to Dashboard
              </button>
              <button
                @click="handleSignOut"
                class="w-full px-4 py-2 text-left text-sm text-content hover:bg-surface-hover flex items-center gap-2"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9" />
                </svg>
                Sign Out
              </button>
            </div>
          </div>
        </div>

        <!-- Balance -->
        <div class="mt-5 flex items-end justify-between">
          <button
            @click="refreshAccount"
            class="text-left hover:opacity-80 transition-opacity"
            :class="{ 'cursor-wait': isCloudLoading }"
            title="Click to refresh"
          >
            <div class="text-[11px] font-semibold uppercase tracking-wider text-content-muted mb-2">Balance</div>
            <div v-if="isFirstLoad" class="h-8 w-28 rounded-md bg-white/10 animate-pulse"></div>
            <span v-else-if="cloudError && !cloudUser" class="text-3xl font-bold text-content-muted">—</span>
            <span v-else class="text-3xl font-bold bg-gradient-to-r from-teal-600 to-indigo-600 dark:from-cyan-400 dark:to-indigo-400 bg-clip-text text-transparent">
              {{ formatBalance(cloudUser?.credits) }}
            </span>
          </button>

          <!-- Action: skeleton while first loading, then Add Balance (paid) / Get Started (free) -->
          <div v-if="isFirstLoad" class="h-9 w-28 rounded-lg bg-white/10 animate-pulse"></div>
          <button
            v-else-if="hasPaidSubscription"
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
        <p v-if="!isFirstLoad && !hasPaidSubscription && (!cloudError || cloudUser)" class="text-sm text-content-tertiary mt-3">
          Subscribe to Stimma Cloud for hosted image and video generation, or configure your own providers.
        </p>
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

      <!-- Usage Card - show for paid tiers (and optimistically during first load to hold layout) -->
      <div v-if="hasPaidSubscription || isFirstLoad" class="rounded-xl border border-edge bg-surface-raised p-5">
        <div class="text-sm font-semibold text-content mb-4">Usage</div>

        <div class="grid grid-cols-2 gap-5">
          <!-- Session window -->
          <div class="flex flex-col gap-2">
            <div class="flex items-baseline justify-between">
              <span class="text-[11px] font-semibold text-content-muted uppercase tracking-wider">Session</span>
              <div v-if="isFirstLoad" class="h-4 w-9 rounded bg-white/10 animate-pulse"></div>
              <span v-else-if="cloudUser?.usageWindows?.session" class="text-lg font-semibold text-content">{{ cloudUser.usageWindows.session.percentUsed }}%</span>
              <span v-else class="text-sm text-content-muted">Idle</span>
            </div>
            <div class="h-1.5 bg-white/[0.07] rounded-full overflow-hidden">
              <div
                v-if="!isFirstLoad && cloudUser?.usageWindows?.session"
                class="h-full rounded-full transition-all duration-300"
                :class="cloudUser.usageWindows.session.percentUsed > 95 ? 'bg-red-500' : cloudUser.usageWindows.session.percentUsed > 80 ? 'bg-amber-500' : 'bg-gradient-to-r from-teal-500 to-emerald-500'"
                :style="{ width: cloudUser.usageWindows.session.percentUsed + '%' }"
              ></div>
            </div>
            <div v-if="isFirstLoad" class="h-3 w-32 rounded bg-white/10 animate-pulse"></div>
            <span v-else-if="cloudUser?.usageWindows?.session" class="text-[11px] text-content-muted">Resets {{ formatDate(cloudUser.usageWindows.session.resetsAt) }}</span>
            <span v-else class="text-[11px] text-content-muted">Starts on next request</span>
          </div>

          <!-- Weekly window -->
          <div class="flex flex-col gap-2">
            <div class="flex items-baseline justify-between">
              <span class="text-[11px] font-semibold text-content-muted uppercase tracking-wider">Week</span>
              <div v-if="isFirstLoad" class="h-4 w-9 rounded bg-white/10 animate-pulse"></div>
              <span v-else-if="cloudUser?.usageWindows?.weekly" class="text-lg font-semibold text-content">{{ cloudUser.usageWindows.weekly.percentUsed }}%</span>
              <span v-else class="text-sm text-content-muted">Idle</span>
            </div>
            <div class="h-1.5 bg-white/[0.07] rounded-full overflow-hidden">
              <div
                v-if="!isFirstLoad && cloudUser?.usageWindows?.weekly"
                class="h-full rounded-full transition-all duration-300"
                :class="cloudUser.usageWindows.weekly.percentUsed > 95 ? 'bg-red-500' : cloudUser.usageWindows.weekly.percentUsed > 80 ? 'bg-amber-500' : 'bg-gradient-to-r from-teal-500 to-emerald-500'"
                :style="{ width: cloudUser.usageWindows.weekly.percentUsed + '%' }"
              ></div>
            </div>
            <div v-if="isFirstLoad" class="h-3 w-32 rounded bg-white/10 animate-pulse"></div>
            <span v-else-if="cloudUser?.usageWindows?.weekly" class="text-[11px] text-content-muted">Resets {{ formatDate(cloudUser.usageWindows.weekly.resetsAt) }}</span>
            <span v-else class="text-[11px] text-content-muted">Starts on next request</span>
          </div>
        </div>
      </div>

      <!-- Account Details Card -->
      <div class="rounded-xl border border-edge bg-surface-raised p-5">
        <div class="text-sm font-semibold text-content mb-4">Account</div>
        <div class="grid grid-cols-3 gap-6">
          <div>
            <div class="text-xs text-content-muted mb-1.5">Email</div>
            <button @click="openDashboard" class="text-sm text-content truncate hover:text-content-secondary transition-colors text-left">{{ user.email }}</button>
          </div>
          <div>
            <div class="text-xs text-content-muted mb-1.5">Plan</div>
            <div v-if="isFirstLoad" class="h-5 w-14 rounded bg-white/10 animate-pulse"></div>
            <div v-else class="flex items-center gap-2">
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
            <div class="text-xs text-content-muted mb-1.5">Member Since</div>
            <div v-if="isFirstLoad" class="h-4 w-28 rounded bg-white/10 animate-pulse"></div>
            <div v-else-if="cloudUser?.createdAt" class="text-sm text-content">{{ formatDate(cloudUser.createdAt) }}</div>
            <div v-else class="text-sm text-content-muted">—</div>
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
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'
import { isTauri } from '../../../apiConfig'

const props = defineProps({
  toolProviders: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'navigate'])

const { user, authError, signOut, signInWithBrowser } = useAuth()
const { cloudBaseUrl, cloudUser, isCloudLoading, cloudError, fetchCloudAccount, ensureCloudBaseUrl, formatBalance, getPlanDisplayName } = useCloudAccount()
const { privacyLockdownActive } = usePrivacyLockdown()

const showMenu = ref(false)
const isConnecting = ref(false)
const connectError = ref('')

// First load = fetching with no data yet. Drives skeletons so the layout
// is fully reserved and nothing reflows when data lands. Once cloudUser is
// cached (module-scoped), reopening settings skips skeletons entirely.
const isFirstLoad = computed(() => isCloudLoading.value && !cloudUser.value)

// Signed-out CTA state: with a working local stack, cloud is pitched as an
// addition; with nothing connected, it's the missing piece + local setup links.
const hasLocalTools = computed(() =>
  props.toolProviders.some(p => p.id !== 'stimma-cloud' && p.enabled !== false && p.status === 'connected')
)

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
