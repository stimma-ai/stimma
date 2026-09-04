<template>
  <!-- The rows of the Stimma Server settings section. Everything here asks
       MAIN about the machine the user is sitting at, never the server the
       window is on (see loadStatus). -->
  <section>
    <div>
      <SettingRow label="Enable server">
        <template #description>
          Serve this library and its tools to your other Stimma installs.
          <button
            class="text-accent hover:text-accent-hi hover:underline cursor-pointer bg-transparent border-none p-0"
            @click="openDocs"
          >Learn more ↗</button>
          <span v-if="error" class="block mt-1 text-red-500">{{ error }}</span>
          <span v-else-if="status?.servingError" class="block mt-1 text-red-500">
            Could not start serving: {{ status.servingError }}
          </span>
        </template>
        <button
          @click="toggleServing"
          :disabled="saving"
          :aria-pressed="serving"
          class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:opacity-60"
          :class="serving ? 'bg-accent' : 'bg-surface-hover'"
        >
          <span
            class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
            :class="serving ? 'translate-x-5' : 'translate-x-0'"
          />
        </button>
      </SettingRow>

      <!-- Editable in place: the default is the OS hostname, which is often
           neither unique nor what you would call the machine. No modal — the
           field is the affordance. -->
      <div
        class="flex items-center justify-between gap-4 py-2.5 border-t border-edge-subtle"
      >
        <div class="min-w-0">
          <div class="text-[13px] text-content">Name</div>
          <div class="text-[11.5px] text-content-tertiary">How this server appears to your other installs.</div>
        </div>
        <input
          v-model="nameDraft"
          class="text-xs font-mono text-content text-right bg-transparent border border-transparent rounded px-1.5 py-0.5 min-w-0 max-w-[240px] focus:outline-none focus:border-accent hover:border-edge-subtle transition-colors"
          :placeholder="status?.deviceName || 'Server name'"
          @blur="commitName"
          @keydown.enter="$event.target.blur()"
          @keydown.esc="nameDraft = status?.deviceName || ''"
        />
      </div>

      <!-- The addresses this install is advertising, for the people who can
           read them: a missing tailnet address or a VPN interface crowding
           the list is visible here before it becomes a support thread. Bare
           mono chips, wrapping under the description, so a Docker host with
           a dozen bridges just takes another line. Ports are noise for this.
           How to reach it from another network is the docs' job. -->
      <div v-if="serving" class="py-2.5 border-t border-edge-subtle">
        <div class="text-[13px] text-content">Listening on</div>
        <div class="text-[11.5px] text-content-tertiary">To share outside of your network, use Tailscale or another VPN.</div>
        <div class="mt-2 flex flex-wrap gap-1">
          <span
            v-for="host in listeningHosts"
            :key="host"
            class="px-1.5 py-0.5 rounded bg-overlay-subtle font-mono text-[11px] leading-tight text-content-secondary tabular-nums"
            >{{ host }}</span
          >
          <span v-if="!listeningHosts.length" class="text-[11px] text-content-muted">No network found</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import SettingRow from '../SettingRow.vue'
import { desktop } from '../../../desktop'
import { useMultiDevice, SERVER_DOCS_URL } from '../../../composables/useMultiDevice'

const { refresh, loadSelf } = useMultiDevice()

const status = ref(null)
const saving = ref(false)
const error = ref('')
const nameDraft = ref('')

const serving = computed(() => status.value?.serving === true)

/** Advertised addresses, LAN first then tailnet, as the registry orders them. */
const listeningHosts = computed(() => {
  const hosts = (status.value?.routes || []).map((r) => r?.host).filter(Boolean)
  return [...new Set(hosts)]
})

// Everything below asks MAIN about the machine the user is sitting at. Going
// through the API base would answer for whichever device the window is
// driving, so on a satellite this block would describe — and toggle — the
// remote install while labelled as this one.
async function loadStatus() {
  try {
    status.value = await desktop.mdLocalStatus()
    nameDraft.value = status.value?.deviceName || ''
  } catch (e) {
    console.warn('[MultiDevice] status failed:', e)
  }
}

async function commitName() {
  const name = nameDraft.value.trim()
  if (!name || name === status.value?.deviceName) {
    nameDraft.value = status.value?.deviceName || ''
    return
  }
  error.value = ''
  try {
    status.value = await desktop.mdRenameLocal(name)
    nameDraft.value = status.value?.deviceName || ''
    await Promise.all([refresh(), loadSelf()])
  } catch (e) {
    error.value = String(e.message || e)
    nameDraft.value = status.value?.deviceName || ''
  }
}

async function toggleServing() {
  saving.value = true
  error.value = ''
  try {
    status.value = await desktop.mdSetLocalServing(!serving.value)
    await refresh()
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    saving.value = false
  }
}

function openDocs() {
  void desktop.openExternal(SERVER_DOCS_URL)
}


onMounted(async () => {
  await loadStatus()
  await refresh()
})
</script>
