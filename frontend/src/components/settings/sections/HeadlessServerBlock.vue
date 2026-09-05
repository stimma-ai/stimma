<template>
  <section v-if="server?.headless" class="mb-7 rounded-lg border border-edge-subtle p-5" aria-label="Server status">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="text-base font-medium text-content">{{ serverName }}</h3>
        <p class="mt-1 text-xs text-content-tertiary">Server hosting this library</p>
      </div>
      <UpdatePill v-if="baseRequired" label="Docker update needed" warning @click="showDocker = !showDocker" />
      <UpdatePill v-else-if="serverBusy" :label="statusLabel" busy disabled />
      <UpdatePill v-else-if="serverAvailable" label="Update server" @click="act('update')" />
    </div>
    <div class="mt-5 flex items-center gap-2 text-sm text-content">
      <Spinner v-if="serverBusy" size="sm" />
      <StatusDot v-else bucket="done" />
      <span>{{ statusLabel }}</span>
    </div>
    <div class="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-content-secondary">
      <span>Stimma <span class="font-mono text-content">{{ server.version || 'Starting' }}</span></span>
      <span>Docker <span class="font-mono text-content">{{ server.bootstrapVersion }}</span></span>
    </div>
    <p class="mt-2 text-xs text-content-tertiary">Updates on startup{{ server.updateWindow ? ` · Nightly, ${server.updateWindow} (${server.timezone})` : '' }}</p>
    <p v-if="error || server.error" role="status" class="mt-3 text-xs text-amber-500">{{ error || server.error }}</p>
    <div class="mt-4 flex flex-wrap items-center gap-2">
      <Button variant="ghost" size="sm" :disabled="serverBusy" @click="act('check')">Check for updates</Button>
      <Button variant="ghost" size="sm" :disabled="serverBusy" @click="confirmRestart = true">Restart server…</Button>
      <Button v-if="baseAvailable && !baseRequired" variant="ghost" size="sm" @click="showDocker = !showDocker">Docker update available</Button>
    </div>
    <div v-if="showDocker" class="mt-4 space-y-2 text-xs text-content-secondary">
      <p>On {{ serverName }}, in the folder containing compose.yaml:</p>
      <pre class="whitespace-pre-wrap font-mono select-text text-content">docker compose pull
docker compose up -d</pre>
    </div>
    <ConfirmDialog :show="confirmRestart" :title="`Restart ${serverName}?`" message="Connected clients will briefly disconnect."
      confirm-label="Restart server" nested @cancel="confirmRestart = false" @confirm="restart" />
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useServerUpdater } from '../../../composables/useServerUpdater'
import Button from '../../ui/Button.vue'
import UpdatePill from '../../ui/UpdatePill.vue'
import Spinner from '../../ui/Spinner.vue'
import StatusDot from '../../ui/StatusDot.vue'
import ConfirmDialog from '../../ui/ConfirmDialog.vue'
const { server, serverName, serverAvailable, serverBusy, baseRequired, baseAvailable, statusLabel, error, act } = useServerUpdater()
const showDocker = ref(false)
const confirmRestart = ref(false)
function restart() { confirmRestart.value = false; void act('restart') }
</script>
