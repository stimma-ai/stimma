<template>
  <div class="space-y-8">
    <div>
      <h3 class="text-xs font-semibold text-content-secondary">MCP</h3>
      <p class="mt-2 text-sm leading-relaxed text-content-tertiary">
        Let a connected assistant work with this profile’s library, tools, Flows and agent.
        Stimma must be running for the connection to work.
      </p>
    </div>
    <p v-if="error" role="alert" class="text-sm text-red-400">{{ error }}</p>
    <label class="flex items-center justify-between gap-4 text-sm text-content">
      <span>Enable MCP for this profile</span>
      <input type="checkbox" :checked="state.enabled" :disabled="busy" class="h-4 w-4 accent-accent" @change="setEnabled($event.target.checked)" />
    </label>
    <template v-if="state.enabled">
      <div class="space-y-3">
        <h4 class="text-xs font-semibold text-content-secondary">Connect an assistant</h4>
        <p class="text-sm text-content-tertiary">Download a connection file, then install it with the Stimma CLI. Each assistant gets its own connection.</p>
        <Button :disabled="busy" @click="connect">Download connection file</Button>
        <p v-if="installCommand" class="text-xs text-content-tertiary">Run this command with the downloaded file:</p>
        <pre v-if="installCommand" class="overflow-x-auto rounded-md bg-overlay-subtle p-3 text-xs text-content">{{ installCommand }}</pre>
        <p class="text-xs leading-relaxed text-content-tertiary">The installer prints the MCP configuration to add to your assistant. The connection file contains a private credential; keep it on your own machine.</p>
      </div>
      <div class="space-y-3">
        <h4 class="text-xs font-semibold text-content-secondary">Unlocking</h4>
        <p class="text-sm leading-relaxed text-content-tertiary">Give your existing profile PIN to the assistant in chat when it asks. A PIN shared with an assistant lets it unlock again until you change the PIN. Stimma does not save the PIN in its MCP logs, but it remains in your assistant’s chat history.</p>
        <p class="text-sm leading-relaxed text-content-tertiary">Chats using the same configured connection share its unlock. It locks after {{ state.idle_timeout_minutes }} minutes without content activity. Locking the desktop window does not lock external access.</p>
        <Button variant="secondary" :disabled="busy" @click="lockAll">Lock external access</Button>
      </div>
      <div>
        <h4 class="mb-3 text-xs font-semibold text-content-secondary">Connections</h4>
        <p v-if="!state.clients.length" class="text-sm text-content-tertiary">No assistants connected yet.</p>
        <div class="divide-y divide-edge-subtle">
          <div v-for="client in state.clients" :key="client.id" class="flex items-center justify-between gap-4 py-3">
            <div>
              <p class="text-sm text-content">{{ client.name }}</p>
              <p class="mt-1 text-xs text-content-tertiary">{{ client.unlocked ? 'Unlocked' : 'Locked' }}</p>
            </div>
            <Button variant="secondary" :disabled="busy" @click="disconnect(client.id)">Disconnect</Button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import Button from '../../ui/Button.vue'
const state = ref({ enabled: false, clients: [], idle_timeout_minutes: 30 })
const error = ref('')
const busy = ref(false)
const installCommand = ref('')
let timer
async function refresh() {
  try { state.value = (await axios.get(`${getApiBase()}/mcp/settings`)).data }
  catch { error.value = 'Could not load MCP settings.' }
}
async function perform(fn) {
  busy.value = true
  error.value = ''
  try { await fn(); await refresh() }
  catch { error.value = 'Could not update this connection. Check that Stimma is running.' }
  finally { busy.value = false }
}
function setEnabled(enabled) { return perform(() => axios.put(`${getApiBase()}/mcp/settings`, { enabled })) }
function lockAll() { return perform(() => axios.post(`${getApiBase()}/mcp/lock`)) }
function disconnect(id) { return perform(() => axios.delete(`${getApiBase()}/mcp/clients/${id}`)) }
function connect() {
  return perform(async () => {
    const { data } = await axios.post(`${getApiBase()}/mcp/clients`, { name: 'Assistant' })
    const filename = `${data.connection.alias}.stimma-mcp.json`
    const url = URL.createObjectURL(new Blob([JSON.stringify(data.connection, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    installCommand.value = `stimma mcp install "${filename}"`
  })
}
onMounted(() => { refresh(); timer = setInterval(refresh, 10000) })
onUnmounted(() => clearInterval(timer))
</script>
