<template>
  <div class="max-w-[720px] space-y-6">
    <header>
      <div class="flex items-center gap-3">
        <h3 class="font-brand text-xl font-semibold text-content">MCP</h3>
        <span class="shrink-0 rounded border border-edge-subtle px-1 py-0.5 text-[8px] font-normal leading-none text-content-tertiary">EXPERIMENTAL</span>
        <a href="https://docs.stimma.ai/mcp/" target="_blank" rel="noopener noreferrer" class="ml-auto shrink-0 text-sm text-accent-hi hover:text-accent" @click.prevent="openGuide">Learn more ↗</a>
      </div>
      <p class="mt-2 text-sm leading-relaxed text-content-secondary">
        Stimma’s built-in agent is the first choice for most creative work. Use MCP (Model Context Protocol)
        to bring this profile’s library and creative tools into another agent’s environment, such as a coding
        agent or an assistant connected to your other systems.
      </p>
      <p class="mt-2 text-sm leading-relaxed text-content-secondary">
        We’re still learning how this works for people. Please let us know how it goes and where you get stuck.
      </p>
    </header>

    <p v-if="error" role="alert" class="text-sm text-red-400">{{ error }}</p>

    <label class="flex cursor-pointer items-center justify-between gap-6 py-2.5">
      <span class="text-sm text-content">{{ enableLabel }}</span>
      <span class="relative inline-flex shrink-0 items-center">
        <input type="checkbox" role="switch" :aria-label="enableLabel" class="peer sr-only" :checked="state.enabled" :disabled="busy || loading" @change="setEnabled($event.target.checked)" />
        <span class="peer h-5 w-9 rounded-full bg-surface-hover after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-accent peer-checked:after:translate-x-full peer-disabled:opacity-50" />
      </span>
    </label>

    <section aria-labelledby="mcp-connections-heading" :class="!state.enabled && 'pointer-events-none opacity-40'" :aria-disabled="!state.enabled">
      <div class="flex items-center justify-between gap-4">
        <h4 id="mcp-connections-heading" class="text-sm font-semibold text-content">Connections</h4>
        <Button size="sm" :disabled="busy || !state.enabled" @click="showNamePrompt = true">+ New</Button>
      </div>

      <div v-if="currentSetup" class="mt-4 space-y-3 rounded-lg border border-edge p-4" data-testid="mcp-new-connection">
        <h5 class="text-sm font-semibold text-content">{{ currentSetup.name }} is ready to connect</h5>
        <p class="text-xs text-content-secondary">Copy the setup request and paste it into your coding agent.</p>
        <Button size="sm" @click="copySetupRequest">{{ copied === 'request' ? 'Copied' : 'Copy setup request' }}</Button>
        <p class="mt-1 text-xs leading-relaxed text-content-secondary">
          For manual setup, use the URL and key below.
          <span class="text-amber-400">The key is shown only once.</span>
          If you lose it, remove this connection and make a new one.
        </p>
        <div class="mt-4 space-y-3">
          <div>
            <p class="mb-1.5 text-xs text-content-tertiary">Server URL</p>
            <div class="flex h-9 items-center gap-1 rounded-md border border-edge bg-base pl-3 pr-1">
              <code class="min-w-0 flex-1 truncate font-mono text-xs text-content select-text">{{ serverUrl(currentSetup.connection) }}</code>
              <Button variant="ghost" size="sm" @click="copy('url', serverUrl(currentSetup.connection))">{{ copied === 'url' ? 'Copied' : 'Copy URL' }}</Button>
            </div>
            <p v-if="isRemote" class="mt-1.5 text-xs leading-relaxed text-content-tertiary" data-testid="mcp-relay-note">
              This address is on this computer, not {{ activeDeviceName }}. Stimma forwards it to {{ activeDeviceName }} while it’s open, so the assistant never needs to reach the server directly.
            </p>
          </div>
          <div>
            <p class="mb-1.5 text-xs text-content-tertiary">Key <span class="text-content-muted">(use as a Bearer token)</span></p>
            <div class="flex h-9 items-center gap-1 rounded-md border border-edge bg-base pl-3 pr-1">
              <code class="min-w-0 flex-1 truncate font-mono text-xs text-content select-text">{{ revealed ? currentSetup.connection.credential : '••••••••••••••••••••••••' }}</code>
              <Button variant="ghost" size="sm" @click="revealed = !revealed">{{ revealed ? 'Hide' : 'Reveal' }}</Button>
              <Button variant="ghost" size="sm" @click="copy('key', currentSetup.connection.credential)">{{ copied === 'key' ? 'Copied' : 'Copy key' }}</Button>
            </div>
          </div>
        </div>
        <div class="mt-4 flex items-center justify-between gap-4">
          <p class="text-xs text-content-tertiary">Not sure where these go? <a href="https://docs.stimma.ai/mcp/" target="_blank" rel="noopener noreferrer" class="text-accent-hi hover:text-accent" @click.prevent="openGuide">Learn more ↗</a></p>
          <Button @click="finishSetup">Done</Button>
        </div>
      </div>

      <div v-else-if="!state.clients.length" class="mt-4 py-2.5">
        <p class="text-sm text-content">No assistants connected yet</p>
        <p class="mt-1 text-xs text-content-tertiary">Click <em>+ New</em>, give it a name like “Claude Desktop”, and you’ll get a URL and key to give your assistant.</p>
      </div>

      <div v-if="state.clients.length" class="mt-2 divide-y divide-edge-subtle">
        <div v-for="client in state.clients" :key="client.id" class="flex items-center justify-between gap-3 py-2.5" data-testid="mcp-connection-row">
          <div class="flex min-w-0 items-center gap-2.5">
            <span class="h-2 w-2 shrink-0 rounded-full" :class="client.unlocked ? 'bg-green-500 shadow-[0_0_0_3px_rgba(34,197,94,.18)]' : 'bg-content-muted'" aria-hidden="true" />
            <div class="min-w-0">
              <p class="truncate text-sm text-content">{{ client.name }}</p>
              <p class="mt-0.5 text-xs text-content-tertiary">
                Created {{ formatDate(client.created_at) }} ·
                {{ client.unlocked ? 'Active now' : client.last_used_at ? `Last used ${formatRelative(client.last_used_at)}` : 'Never used' }}
              </p>
            </div>
          </div>
          <div class="relative shrink-0">
            <button type="button" class="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-overlay-subtle hover:text-content" :aria-label="`Options for ${client.name}`" aria-haspopup="menu" :aria-expanded="menuFor === client.id" @click.stop="menuFor = menuFor === client.id ? '' : client.id">
              <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><circle cx="4" cy="10" r="1.6" /><circle cx="10" cy="10" r="1.6" /><circle cx="16" cy="10" r="1.6" /></svg>
            </button>
            <div v-if="menuFor === client.id" role="menu" class="absolute right-0 top-8 z-menu min-w-[170px] rounded-lg border border-edge bg-surface p-1 shadow-xl">
              <button type="button" role="menuitem" class="block w-full rounded px-2.5 py-1.5 text-left text-sm text-content hover:bg-surface-hover" @click="startRename(client)">Rename…</button>
              <div class="my-1 border-t border-edge-subtle" />
              <button type="button" role="menuitem" class="block w-full rounded px-2.5 py-1.5 text-left text-sm text-red-400 hover:bg-red-500/10" @click="disconnect(client.id)">Remove connection</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <Modal :show="showNamePrompt" size="sm" @close="showNamePrompt = false">
      <template #header><h4 class="text-base font-semibold text-content">New connection</h4></template>
      <form class="px-6 py-4" @submit.prevent="connect">
        <p class="text-xs text-content-secondary">Name it after the assistant you’re connecting so you can tell keys apart later.</p>
        <input ref="nameInput" v-model="newName" type="text" aria-label="Connection name" maxlength="80" class="mt-3 w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" />
        <div class="mt-2.5 flex flex-wrap gap-1.5">
          <button v-for="suggestion in suggestions" :key="suggestion" type="button" class="rounded-full border border-edge px-2.5 py-1 text-xs text-content-secondary hover:border-accent/50 hover:text-content" @click="newName = suggestion">{{ suggestion }}</button>
        </div>
      </form>
      <template #footer>
        <Button variant="secondary" @click="showNamePrompt = false">Cancel</Button>
        <Button :loading="busy" :disabled="!newName.trim()" @click="connect">Create &amp; show key</Button>
      </template>
    </Modal>

    <Modal :show="!!renaming" size="sm" @close="renaming = null">
      <template #header><h4 class="text-base font-semibold text-content">Rename connection</h4></template>
      <form class="px-6 py-4" @submit.prevent="rename">
        <input ref="renameInput" v-model="renameValue" type="text" aria-label="Connection name" maxlength="80" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" />
      </form>
      <template #footer>
        <Button variant="secondary" @click="renaming = null">Cancel</Button>
        <Button :loading="busy" :disabled="!renameValue.trim()" @click="rename">Save</Button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import axios from 'axios'
import { getApiBase, getBackendOrigin } from '../../../apiConfig'
import { useMultiDevice } from '../../../composables/useMultiDevice'
import { desktop } from '../../../desktop'
import { copyToClipboard } from '../../../utils/clipboard'
import Button from '../../ui/Button.vue'
import Modal from '../../ui/Modal.vue'

const props = defineProps({ hasMultipleProfiles: Boolean })
const enableLabel = computed(() => `Enable MCP Server${props.hasMultipleProfiles ? ' for this profile' : ''}`)

const suggestions = ['Claude Desktop', 'Claude Code', 'ChatGPT', 'Codex', 'Cursor', 'Grok', 'OpenCode']

const { isRemote, activeDeviceName } = useMultiDevice()

// The URL an assistant on this machine can actually open. In the desktop app
// that is the shell's loopback proxy, which forwards to whichever install the
// window is on — the only route to a remote server, whose backend listens on
// loopback behind the TLS device gate. Outside the shell (dev, acceptance)
// the backend's own address is on this machine and works as-is.
function serverUrl(connection) {
  const origin = getBackendOrigin()
  return origin && connection.path ? `${origin}${connection.path}` : connection.endpoint
}

const state = ref({ enabled: false, clients: [] })
const error = ref('')
const busy = ref(false)
const loading = ref(true)
const currentSetup = ref(null)
const copied = ref('')
const revealed = ref(false)
const showNamePrompt = ref(false)
const newName = ref('')
const nameInput = ref(null)
const renaming = ref(null)
const renameValue = ref('')
const renameInput = ref(null)
const menuFor = ref('')
let timer
let copiedTimer
let disposed = false
let refreshVersion = 0

watch(showNamePrompt, async open => {
  if (!open) return
  newName.value = suggestions.find(s => !state.value.clients.some(c => c.name === s)) || ''
  await nextTick()
  nameInput.value?.focus()
  nameInput.value?.select()
})

async function refresh() {
  const version = ++refreshVersion
  const { data } = await axios.get(`${getApiBase()}/mcp/settings`)
  if (disposed || version !== refreshVersion) return
  state.value = data
  if (currentSetup.value && !data.clients.some(client => client.id === currentSetup.value.id)) {
    currentSetup.value = null
  }
}
async function perform(fn) {
  if (busy.value) return
  busy.value = true
  ++refreshVersion
  error.value = ''
  try { await fn(); await refresh() }
  catch { error.value = 'Could not update this connection. Check that Stimma is running and try again.' }
  finally { busy.value = false }
}
function setEnabled(enabled) {
  revealed.value = false
  menuFor.value = ''
  return perform(() => axios.put(`${getApiBase()}/mcp/settings`, { enabled }))
}
function disconnect(id) {
  menuFor.value = ''
  return perform(async () => {
    await axios.delete(`${getApiBase()}/mcp/clients/${id}`)
    if (currentSetup.value?.id === id) currentSetup.value = null
    copied.value = ''
    revealed.value = false
  })
}
function connect() {
  const name = newName.value.trim()
  if (!name || !state.value.enabled) return
  return perform(async () => {
    const { data } = await axios.post(`${getApiBase()}/mcp/clients`, { name })
    if (disposed) return
    currentSetup.value = data
    revealed.value = false
    copied.value = ''
    showNamePrompt.value = false
  })
}
function finishSetup() {
  currentSetup.value = null
  revealed.value = false
  copied.value = ''
}
async function startRename(client) {
  menuFor.value = ''
  renaming.value = client
  renameValue.value = client.name
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
}
function rename() {
  const name = renameValue.value.trim()
  const client = renaming.value
  if (!name || !client) return
  return perform(async () => {
    await axios.patch(`${getApiBase()}/mcp/clients/${client.id}`, { name })
    if (currentSetup.value?.id === client.id) currentSetup.value = { ...currentSetup.value, name }
    renaming.value = null
  })
}
async function copy(field, value) {
  error.value = ''
  if (await copyToClipboard(value)) {
    copied.value = field
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copied.value = '' }, 3000)
  } else {
    error.value = field === 'request'
      ? 'Could not copy the request. Use Copy URL and Copy key to give the connection details to your agent.'
      : field === 'key' ? 'Could not copy. Reveal the key to select and copy it manually.' : 'Could not copy. Select the URL and copy it manually.'
  }
}
function copySetupRequest() {
  const connection = currentSetup.value?.connection
  if (!connection) return
  return copy('request', `Set up Stimma as an MCP server for yourself on this computer.
Use your personal configuration and preserve my existing settings.

Server name: stimma
Transport: Streamable HTTP
Server URL: ${serverUrl(connection)}
Authorization header: Bearer ${connection.credential}

Tell me when it’s ready and whether I need to start a new session.
Setup guide: https://docs.stimma.ai/mcp/`)
}
async function openGuide() {
  try { await desktop.openExternal('https://docs.stimma.ai/mcp/') }
  catch { error.value = 'Could not open the guide. Visit docs.stimma.ai/mcp for setup instructions.' }
}
function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
function formatRelative(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'Just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  return formatDate(iso)
}
function closeMenu() { menuFor.value = '' }
onMounted(async () => {
  window.addEventListener('click', closeMenu)
  try { await refresh() }
  catch { error.value = 'Could not load MCP settings. Reopen this page to try again.' }
  finally { loading.value = false }
  if (!disposed) timer = setInterval(() => { if (!busy.value) refresh().catch(() => {}) }, 10000)
})
onUnmounted(() => { disposed = true; window.removeEventListener('click', closeMenu); clearInterval(timer); clearTimeout(copiedTimer) })
</script>
