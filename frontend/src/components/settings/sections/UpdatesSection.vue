<template>
  <div class="flex flex-col min-h-full">
    <!-- Identity -->
    <div class="flex items-center gap-4 pb-6">
      <img src="/logo.png" alt="Stimma" class="w-16 h-16 rounded-lg border border-edge bg-surface" />
      <div>
        <div class="flex items-center gap-2.5">
          <span class="font-brand lowercase tracking-[0.12em] text-xl font-semibold text-content">stimma</span>
          <span
            v-if="channelBadge"
            class="px-2 py-0.5 rounded text-xs font-medium bg-accent/15 text-accent"
          >
            {{ channelBadge }}
          </span>
        </div>
        <div class="flex items-center gap-2 mt-1.5 text-sm text-content-secondary">
          <span>Version {{ appVersion }}</span>
          <code
            v-if="commitHash"
            class="text-xs text-content-tertiary bg-overlay-subtle px-1.5 py-0.5 rounded font-mono"
          >
            {{ commitHash }}
          </code>
          <button
            @click="copyBuildInfo"
            class="flex items-center gap-1 text-xs text-content-muted hover:text-content-secondary transition-colors"
            title="Copy build info"
          >
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15V5a2 2 0 0 1 2-2h10" />
            </svg>
            {{ copied ? 'Copied' : 'Copy' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Update status -->
    <div class="rounded-lg bg-overlay-faint px-4 py-3.5">
      <div class="flex items-center gap-3">
        <template v-if="updatesBlockedByPrivacyLockdown">
          <StatusDot bucket="queued" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content">Updates are paused</div>
            <div class="text-xs text-content-muted mt-0.5">
              Privacy Lockdown is on. Stimma will not check for or download updates.
            </div>
          </div>
        </template>

        <template v-else-if="!updatesEnabled">
          <StatusDot bucket="queued" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content">Updates are not available in this build</div>
          </div>
        </template>

        <template v-else-if="isChecking">
          <div class="w-4 h-4 border-2 border-content-muted border-t-accent rounded-full animate-spin shrink-0"></div>
          <div class="flex-1 min-w-0 text-sm text-content-tertiary">Checking for updates...</div>
        </template>

        <template v-else-if="isDownloading">
          <StatusDot bucket="running" pulse />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content">Installing update...</div>
          </div>
        </template>

        <template v-else-if="pendingRestart">
          <StatusDot bucket="running" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content">Version {{ stagedVersion }} is ready</div>
            <div class="text-xs text-content-muted mt-0.5">
              {{ pendingApply === 'install' ? 'Restart Stimma to install' : 'Restart Stimma to finish installing' }}
            </div>
          </div>
          <Button size="sm" @click="restartToApply()">
            {{ pendingApply === 'install' ? 'Restart & Install' : 'Restart Now' }}
          </Button>
        </template>

        <template v-else-if="availableUpdate">
          <StatusDot bucket="running" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content">Version {{ availableUpdate.version }} is available</div>
            <div v-if="lastCheckedAt" class="text-xs text-content-muted mt-0.5">
              Checked {{ formatRelativeTime(lastCheckedAt) }}
            </div>
          </div>
          <Button size="sm" @click="downloadAndInstallUpdate()">Install Update</Button>
        </template>

        <template v-else>
          <StatusDot bucket="done" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-content">You're on the latest version</div>
            <div v-if="lastCheckedAt" class="text-xs text-content-muted mt-0.5">
              Checked {{ formatRelativeTime(lastCheckedAt) }}
            </div>
          </div>
          <Button variant="secondary" size="sm" @click="checkForUpdates('manual')">Check Now</Button>
        </template>
      </div>
    </div>

    <!-- Update behavior -->
    <div v-if="updatesEnabled" class="mt-7">
      <div class="text-xs font-semibold text-content-secondary mb-2.5">Update behavior</div>
      <div class="grid grid-cols-3 gap-2">
        <button
          v-for="option in policyOptions"
          :key="option.value"
          @click="setUpdatePolicy(option.value)"
          :disabled="updatesBlockedByPrivacyLockdown"
          class="rounded-lg px-3.5 py-3 text-left transition-colors"
          :class="[
            policy === option.value
              ? 'bg-accent/10 text-accent-hi'
              : 'bg-overlay-subtle hover:bg-overlay-hover',
            updatesBlockedByPrivacyLockdown ? 'cursor-not-allowed opacity-60' : '',
          ]"
        >
          <div class="flex items-center gap-2">
            <div
              class="w-3.5 h-3.5 rounded-full border flex items-center justify-center shrink-0"
              :class="policy === option.value ? 'border-accent' : 'border-content-muted'"
            >
              <div v-if="policy === option.value" class="w-1.5 h-1.5 rounded-full bg-accent"></div>
            </div>
            <span class="text-[13px] text-content">{{ option.label }}</span>
          </div>
          <div class="text-xs text-content-tertiary mt-1.5 leading-relaxed">{{ option.description }}</div>
        </button>
      </div>
    </div>

    <!-- Resources -->
    <div class="mt-7">
      <div class="text-xs font-semibold text-content-secondary mb-2.5">Resources</div>
      <div class="divide-y divide-edge-subtle">
        <button
          v-for="link in resourceLinks"
          :key="link.url"
          @click="openExternal(link.url)"
          class="w-full flex items-center gap-3 px-2 -mx-2 py-2.5 text-left rounded-md hover:bg-overlay-subtle transition-colors duration-150"
        >
          <svg class="w-4 h-4 text-content-tertiary shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" v-html="link.icon"></svg>
          <div class="flex-1 min-w-0">
            <div class="text-[13px] text-content">{{ link.title }}</div>
            <div class="text-xs text-content-muted mt-0.5">{{ link.subtitle }}</div>
          </div>
          <svg class="w-3.5 h-3.5 text-content-muted shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
            <path d="M7 17L17 7M9 7h8v8" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Footer -->
    <div class="mt-auto pt-7 flex items-center justify-between text-xs text-content-muted">
      <span>© {{ copyrightYear }} Stimma AI</span>
      <div class="flex gap-4">
        <button @click="openExternal('/link/terms')" class="text-content-tertiary hover:text-content-secondary transition-colors">Terms</button>
        <button @click="openExternal('/link/privacy')" class="text-content-tertiary hover:text-content-secondary transition-colors">Privacy Policy</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { useAppUpdater } from '../../../composables/useAppUpdater'
import { useCloudAccount } from '../../../composables/useCloudAccount'
import { COMMIT_HASH } from '../../../distribution'
import StatusDot from '../../ui/StatusDot.vue'
import Button from '../../ui/Button.vue'

const {
  channel,
  policy,
  updatesEnabled,
  updatesBlockedByPrivacyLockdown,
  isChecking,
  isDownloading,
  lastCheckedAt,
  availableUpdate,
  stagedVersion,
  pendingRestart,
  pendingApply,
  loadPreferences,
  setUpdatePolicy,
  checkForUpdates,
  downloadAndInstallUpdate,
  restartToApply,
} = useAppUpdater()

const policyOptions = [
  {
    value: 'automatic' as const,
    label: 'Automatic',
    description: 'Download and install in the background, applied on next launch.',
  },
  {
    value: 'prompt_all' as const,
    label: 'Notify me',
    description: 'Check for updates and let me choose when to install.',
  },
  {
    value: 'manual' as const,
    label: 'Manual',
    description: 'Only check when I click Check Now.',
  },
]

// All external links route through the cloud's /link/* redirects so
// destinations can be changed remotely (e.g. an expired Discord invite)
// without an app update. The base URL comes from settings, so debug builds
// route through dev.stimma.ai like login does.
const resourceLinks = [
  {
    title: 'stimma.ai',
    subtitle: 'Learn about Stimma',
    url: '/link/site',
    icon: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 2.5 15.4 0 18M12 3c-2.5 2.6-2.5 15.4 0 18"/>',
  },
  {
    title: 'Documentation',
    subtitle: 'Guides for every part of the app',
    url: '/link/docs',
    icon: '<path d="M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19a2 2 0 0 0 2 2h13"/>',
  },
  {
    title: 'GitHub',
    subtitle: 'Source code and issue tracker',
    url: '/link/github',
    icon: '<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>',
  },
  {
    title: 'Discord',
    subtitle: 'Community chat and help',
    url: '/link/discord',
    icon: '<path d="M8.5 17c-2 .5-3.5-.5-4.5-1.5.5-4 1.5-7 3-9.5 1-.5 2.2-.9 3.5-1l.5 1.5c.6-.1 1-.1 1.5 0L13 5c1.3.1 2.5.5 3.5 1 1.5 2.5 2.5 5.5 3 9.5-1 1-2.5 2-4.5 1.5l-.7-1.4c-1.5.5-3.6.5-5.1 0z"/><path d="M9.5 12.5v.5M14.5 12.5v.5"/>',
  },
  {
    title: 'Reddit',
    subtitle: 'r/stimma community',
    url: '/link/reddit',
    icon: '<circle cx="12" cy="14" r="6.5"/><path d="M5.5 12.5a1.8 1.8 0 1 1 2-3M18.5 12.5a1.8 1.8 0 1 0-2-3M12 7.5l.8-3.5 3.2 1"/><circle cx="17" cy="4.5" r="1.2"/><path d="M9.5 14v.5M14.5 14v.5M9.5 17c1.5 1 3.5 1 5 0"/>',
  },
]

const appVersion = ref('unknown')
const copied = ref(false)
const commitHash = COMMIT_HASH
const copyrightYear = new Date().getFullYear()

const channelBadge = computed(() => {
  const value = channel.value
  if (value === 'production') return null
  if (value === 'beta') return 'Beta'
  if (value === 'canary') return 'Canary'
  // Local builds don't set VITE_STIMMA_RELEASE_CHANNEL — that's the debug channel.
  return 'Debug'
})

async function copyBuildInfo() {
  const parts = [`Stimma ${appVersion.value}`]
  if (commitHash) parts.push(`(${commitHash})`)
  if (channelBadge.value) parts.push(channelBadge.value.toLowerCase())
  try {
    await navigator.clipboard.writeText(parts.join(' '))
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    // clipboard unavailable — ignore
  }
}

const { ensureCloudBaseUrl } = useCloudAccount()

async function openExternal(path: string) {
  const base = await ensureCloudBaseUrl()
  const url = `${base.replace(/\/$/, '')}${path}`
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

function formatRelativeTime(value: string): string {
  const date = new Date(value)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays === 1) return 'yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

onMounted(async () => {
  await loadPreferences()
  try {
    appVersion.value = await getVersion()
  } catch {
    appVersion.value = 'unknown'
  }
  // Auto-check when visiting this section
  if (!updatesBlockedByPrivacyLockdown.value) checkForUpdates('manual')
})
</script>
