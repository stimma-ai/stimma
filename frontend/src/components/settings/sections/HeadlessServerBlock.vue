<template>
  <section v-if="server?.headless" class="mb-7 space-y-4">
    <div>
      <h3 class="text-sm font-medium text-content">Connected server</h3>
      <p class="mt-1 text-xs text-content-tertiary">These controls manage the server hosting this library.</p>
    </div>
    <dl class="divide-y divide-edge-subtle text-xs">
      <div class="flex justify-between py-2"><dt class="text-content-tertiary">Stimma version</dt><dd class="font-mono text-content">{{ server.version || 'Starting' }}</dd></div>
      <div class="flex justify-between py-2"><dt class="text-content-tertiary">Docker base image</dt><dd class="font-mono text-content">{{ server.bootstrapVersion }}</dd></div>
      <div class="flex justify-between py-2"><dt class="text-content-tertiary">Status</dt><dd class="text-content">{{ statusLabel }}</dd></div>
      <div v-if="server.availableVersion" class="flex justify-between py-2"><dt class="text-content-tertiary">Latest Stimma version</dt><dd class="font-mono text-content">{{ server.availableVersion }}</dd></div>
      <div class="flex justify-between py-2"><dt class="text-content-tertiary">Automatic updates</dt><dd class="text-content">On startup{{ server.updateWindow ? ` and ${server.updateWindow} (${server.timezone})` : '' }}</dd></div>
    </dl>
    <p v-if="server.bootstrapUpdateRequired || server.bootstrapUpdateAvailable" class="text-xs text-amber-500">
      Docker base {{ server.latestBootstrapVersion }} {{ server.bootstrapUpdateRequired ? 'is required for the next Stimma update' : 'is available' }}.
      On the server, run <code class="font-mono select-text">docker compose pull &amp;&amp; docker compose up -d</code>. Keep the same image tag and data volume.
    </p>
    <p v-if="error || server.error" role="status" class="text-xs text-amber-500">{{ error || server.error }}</p>
    <p v-if="notice" role="status" class="text-xs text-content-secondary">{{ notice }}</p>
    <div class="flex flex-wrap gap-2">
      <Button variant="secondary" size="sm" :disabled="busy" @click="act('check')">Check for updates</Button>
      <Button v-if="server.availableVersion && server.availableVersion !== server.version" size="sm" :disabled="busy || server.bootstrapUpdateRequired" @click="confirmAction = 'update'">Update server</Button>
      <Button variant="secondary" size="sm" :disabled="busy" @click="confirmAction = 'restart'">Restart server</Button>
    </div>
    <div v-if="confirmAction" class="space-y-3">
      <p class="text-xs text-content-secondary">{{ confirmAction === 'update' ? 'Install the latest Stimma update and restart this server?' : 'Restart this server?' }} Stimma will wait for active work to finish. Connected clients will briefly disconnect.</p>
      <div class="flex gap-2">
        <Button size="sm" @click="act(confirmAction)">{{ confirmAction === 'update' ? 'Update and restart' : 'Restart' }}</Button>
        <Button variant="ghost" size="sm" @click="confirmAction = null">Cancel</Button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getApiBase } from '../../../apiConfig'
import Button from '../../ui/Button.vue'
const server = ref<any>(null)
const error = ref('')
const notice = ref('')
const confirmAction = ref<'update' | 'restart' | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const labels: Record<string, string> = { ready: 'Running', starting: 'Starting', checking: 'Checking for updates', downloading: 'Downloading update', waiting_for_idle: 'Waiting for active work to finish', restarting: 'Restarting', error: 'Needs attention' }
const statusLabel = computed(() => labels[server.value?.status] || server.value?.status)
const busy = computed(() => !['ready', 'error'].includes(server.value?.status))
async function refresh() {
  try {
    const response = await fetch(`${getApiBase()}/headless/status`)
    if (response.status === 404) { server.value = null; return }
    if (!response.ok) throw new Error('Server is reconnecting. Status will refresh automatically.')
    server.value = await response.json()
    error.value = ''
    if (['ready', 'error'].includes(server.value.status)) notice.value = ''
  } catch (e: any) { if (server.value?.headless) error.value = e.message }
  finally { if (!disposed) timer = setTimeout(refresh, 3000) }
}
async function act(action: string) {
  confirmAction.value = null
  error.value = ''
  try {
    const response = await fetch(`${getApiBase()}/headless/${action}`, { method: 'POST' })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Server operation failed')
    server.value = data
    notice.value = action === 'check' ? 'Checking for server updates…' : 'Request accepted. Waiting for the server to finish active work.'
  } catch (e: any) { error.value = e.message }
}
onMounted(refresh)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>
