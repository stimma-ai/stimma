<template>
  <div v-if="show" ref="root" class="relative flex items-center gap-1" data-update-controls>
    <UpdatePill :label="label" :busy="busy" :warning="baseRequired" @click="primaryAction" />
    <button type="button" class="h-7 w-6 rounded-md text-content-secondary hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
      aria-label="Update details" :aria-expanded="open" @click="open = !open">⌄</button>
    <div v-if="open" class="absolute right-0 top-full z-menu mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-edge bg-surface p-4 shadow-lg"
      role="dialog" aria-label="Updates" @keydown.esc.stop="open = false">
      <div class="mb-2 flex items-center justify-between"><h3 class="text-sm font-medium text-content">Updates</h3>
        <button type="button" class="text-content-tertiary hover:text-content" aria-label="Close update details" @click="open = false">×</button>
      </div>
      <div class="divide-y divide-edge-subtle">
        <div class="flex items-center justify-between gap-4 py-3">
          <div><p class="text-sm text-content">{{ THIS_MACHINE_LABEL }}</p><p class="mt-1 text-xs font-mono text-content-tertiary">{{ currentVersion }}<span v-if="machineAvailable"> → {{ stagedVersion || availableVersion }}</span></p></div>
          <span v-if="isDownloading" class="text-xs text-content-secondary">Updating…</span>
          <Button v-else-if="machineAvailable" variant="ghost" size="sm" :disabled="busy" @click="updateMachine">Update</Button>
          <span v-else class="text-xs text-content-tertiary">Up to date</span>
        </div>
        <div v-if="server" class="flex items-center justify-between gap-4 py-3">
          <div><p class="text-sm text-content">{{ serverName }}</p><p class="mt-1 text-xs font-mono text-content-tertiary">{{ server.version }}<span v-if="serverAvailable"> → {{ server.availableVersion }}</span></p></div>
          <span v-if="serverBusy" class="text-xs text-content-secondary">Updating…</span>
          <span v-else-if="baseRequired" class="text-xs text-amber-500">Needs Docker update</span>
          <Button v-else-if="serverAvailable" variant="ghost" size="sm" :disabled="busy" @click="act('update')">Update</Button>
          <span v-else class="text-xs text-content-tertiary">Up to date</span>
        </div>
        <div v-if="baseRequired || baseAvailable" class="py-3 text-xs text-content-secondary">
          <p class="text-amber-500">Docker {{ server?.latestBootstrapVersion }} available on {{ serverName }}</p>
          <p class="mt-2">On the server, in the folder containing compose.yaml:</p>
          <pre class="mt-2 whitespace-pre-wrap font-mono select-text text-content">docker compose pull
docker compose up -d</pre>
        </div>
      </div>
      <p v-if="error" class="mt-2 text-xs text-amber-500" role="status">{{ error }}</p>
      <Button v-if="installableCount > 1 && !busy" class="mt-3" size="sm" @click="updateAll">Update all · {{ installableCount }}</Button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useServerUpdater } from '../composables/useServerUpdater'
import { useAppUpdater } from '../composables/useAppUpdater'
import { THIS_MACHINE_LABEL } from '../composables/useMultiDevice'
import UpdatePill from './ui/UpdatePill.vue'
import Button from './ui/Button.vue'
const { server, serverName, serverAvailable, serverBusy, machineAvailable, machineLabel, baseRequired, baseAvailable,
  busy, installableCount, updateCount, statusLabel, error, updateAll, updateMachine, act } = useServerUpdater()
const { currentVersion, availableVersion, stagedVersion, isDownloading, updatesBlockedByPrivacyLockdown } = useAppUpdater()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const show = computed(() => !updatesBlockedByPrivacyLockdown.value && (updateCount.value > 0 || busy.value))
const label = computed(() => {
  if (serverBusy.value) return statusLabel.value
  if (isDownloading.value) return `Updating ${machineLabel}…`
  if (baseRequired.value) return `Updates · ${updateCount.value}`
  if (installableCount.value > 1) return `Update all · ${installableCount.value}`
  if (serverAvailable.value) return 'Update server'
  if (machineAvailable.value) return `Update ${machineLabel}`
  return 'Docker update available'
})
function primaryAction() { if (busy.value || baseRequired.value || !installableCount.value) open.value = !open.value; else void updateAll() }
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) open.value = false }
function escape(event: KeyboardEvent) { if (event.key === 'Escape') open.value = false }
onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape) })
onUnmounted(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) })
</script>
