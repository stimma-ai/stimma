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

      <div v-else-if="availableUpdate && isDownloading" class="flex items-center gap-2 text-sm text-content-tertiary">
        <div class="w-4 h-4 border-2 border-content-muted border-t-blue-500 rounded-full animate-spin"></div>
        Installing {{ availableUpdate.version }}...
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

      <div v-else class="text-sm text-content-tertiary">
        You're on the latest version.
      </div>

      <!-- Update behavior -->
      <div>
        <div class="text-sm text-content mb-2">Update behavior</div>
        <div class="w-full px-3 py-2 rounded-lg border border-edge bg-surface text-content text-sm">
          Ask before installing
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
  updatesEnabled,
  isChecking,
  isDownloading,
  lastCheckedAt,
  availableUpdate,
  loadPreferences,
  checkForUpdates,
  downloadAndInstallUpdate,
} = useAppUpdater()

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
