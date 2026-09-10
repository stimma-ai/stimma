<template>
  <div v-if="show" class="flex items-center" data-update-controls>
    <UpdatePill :label="label" :busy="busy" :warning="baseRequired" @click="primaryAction" />
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useServerUpdater } from '../composables/useServerUpdater'
import { useAppUpdater } from '../composables/useAppUpdater'
import UpdatePill from './ui/UpdatePill.vue'
const emit = defineEmits<{ 'open-settings': [section: string] }>()
const { serverAvailable, serverBusy, machineAvailable, machineLabel, baseRequired,
  busy, installableCount, updateCount, statusLabel, updateAll } = useServerUpdater()
const { isDownloading, updatesBlockedByPrivacyLockdown } = useAppUpdater()
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
// Anything that can't be installed from the pill itself (a Docker update the
// user has to run by hand, or an update already in progress) lives in Settings.
function primaryAction() {
  if (!busy.value && !baseRequired.value && installableCount.value) return void updateAll()
  emit('open-settings', isDownloading.value && !serverBusy.value ? 'updates' : 'server')
}
</script>
