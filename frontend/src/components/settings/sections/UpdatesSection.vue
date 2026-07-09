<template>
  <div>
    <h3 class="text-base font-medium text-content mb-6">Updates</h3>

    <div class="space-y-6">
      <!-- Current version -->
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm text-content">{{ appVersion }}</div>
          <div v-if="lastCheckedAt" class="text-xs text-content-muted mt-1">
            Checked {{ formatRelativeTime(lastCheckedAt) }}
          </div>
        </div>
        <span class="px-2 py-0.5 rounded text-xs font-medium bg-blue-500/15 text-blue-500">
          {{ channelLabel }}
        </span>
      </div>

      <!-- Update status -->
      <div v-if="!updatesEnabled" class="text-sm text-content-tertiary">
        Updates are not available in this build.
      </div>

      <div v-else-if="isChecking" class="flex items-center gap-2 text-sm text-content-tertiary">
        <div class="w-4 h-4 border-2 border-content-muted border-t-blue-500 rounded-full animate-spin"></div>
        Checking for updates...
      </div>

      <div v-else-if="isDownloading" class="flex items-center gap-2 text-sm text-content-tertiary">
        <div class="w-4 h-4 border-2 border-content-muted border-t-blue-500 rounded-full animate-spin"></div>
        Installing update...
      </div>

      <div v-else-if="pendingRestart" class="flex items-center justify-between">
        <div class="text-sm text-content">
          <template v-if="pendingApply === 'install'">Version {{ stagedVersion }} is ready. Restart to install.</template>
          <template v-else>Version {{ stagedVersion }} installed. Restart to finish.</template>
        </div>
        <button
          @click="restartToApply()"
          class="px-3 py-1.5 bg-blue-500 hover:bg-blue-400 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {{ pendingApply === 'install' ? 'Restart & Install' : 'Restart Now' }}
        </button>
      </div>

      <div v-else-if="availableUpdate" class="flex items-center justify-between">
        <div class="text-sm text-content">
          Version {{ availableUpdate.version }} is available.
        </div>
        <button
          @click="downloadAndInstallUpdate()"
          class="px-3 py-1.5 bg-blue-500 hover:bg-blue-400 text-white rounded-lg text-sm font-medium transition-colors"
        >
          Install Update
        </button>
      </div>

      <div v-else class="flex items-center justify-between">
        <div class="text-sm text-content-tertiary">You're on the latest version.</div>
        <button
          @click="checkForUpdates('manual')"
          class="px-3 py-1.5 rounded-lg border border-edge bg-surface hover:bg-overlay-subtle text-content text-sm font-medium transition-colors"
        >
          Check Now
        </button>
      </div>

      <!-- Update behavior -->
      <div>
        <div class="text-sm text-content mb-2">Update behavior</div>
        <div class="space-y-1.5">
          <button
            v-for="option in policyOptions"
            :key="option.value"
            @click="setUpdatePolicy(option.value)"
            class="w-full flex items-start gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors"
            :class="policy === option.value
              ? 'border-blue-500/50 bg-blue-500/15'
              : 'border-edge bg-surface hover:bg-overlay-subtle'"
          >
            <div
              class="mt-0.5 w-4 h-4 rounded-full border flex items-center justify-center shrink-0"
              :class="policy === option.value ? 'border-blue-500' : 'border-content-muted'"
            >
              <div v-if="policy === option.value" class="w-2 h-2 rounded-full bg-blue-500"></div>
            </div>
            <div>
              <div class="text-sm text-content">{{ option.label }}</div>
              <div class="text-xs text-content-muted mt-0.5">{{ option.description }}</div>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { useAppUpdater } from '../../../composables/useAppUpdater'

const {
  channel,
  policy,
  updatesEnabled,
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
    description: 'Download and install updates in the background, applied the next time you launch Stimma.',
  },
  {
    value: 'prompt_all' as const,
    label: 'Notify me',
    description: 'Check for updates and let me choose when to install.',
  },
  {
    value: 'manual' as const,
    label: 'Manual',
    description: 'Never check automatically. Only check when I click Check Now.',
  },
]

const appVersion = ref('unknown')

const channelLabel = computed(() => {
  const value = channel.value
  if (value === 'production') return 'Stable'
  if (value === 'beta') return 'Beta'
  if (value === 'canary') return 'Canary'
  return 'Dev'
})

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
  checkForUpdates('manual')
})
</script>
