<template>
  <section class="mt-9">
    <h3 class="text-xs font-semibold text-content-secondary">Stimma Server</h3>

    <div class="mt-2">
      <SettingRow label="Enable server">
        <template #description>
          Serve this library and its tools to your other Stimma installs.
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
    </div>

    <!-- The account's roster. Only installs that were OFFERED appear here,
         on this machine or any other. -->
    <div v-if="peers.length" class="mt-6">
      <div class="text-xs font-semibold text-content-secondary">Other servers</div>
      <div class="mt-2">
        <div
          v-for="(device, i) in peers"
          :key="device.deviceId"
          class="flex items-center gap-3 py-2.5"
          :class="i > 0 ? 'border-t border-edge-subtle' : ''"
        >
          <span
            class="w-1.5 h-1.5 rounded-full flex-shrink-0"
            :class="isOnline(device) ? 'bg-green-500' : 'bg-zinc-500'"
          />
          <div class="min-w-0 flex-1">
            <div class="text-[13px] text-content truncate">{{ device.name }}</div>
            <div class="text-[11.5px] text-content-tertiary">
              {{ isOnline(device) ? 'Online now' : `Last seen ${lastSeenLabel(device)}` }}
            </div>
          </div>
          <span
            v-for="tag in deviceTags(device)"
            :key="tag"
            class="px-1.5 py-0.5 rounded bg-overlay-subtle font-mono text-[10px] text-content-muted flex-shrink-0"
            >{{ tag }}</span
          >
          <!-- Housekeeping for stale rows only, so offline rows alone get it:
               removing an online server is undone by its next heartbeat, and
               trust is the account, so this was never a revoke. -->
          <button
            v-if="!isOnline(device)"
            class="p-1.5 rounded text-content-muted hover:text-content hover:bg-overlay-subtle transition-colors cursor-pointer flex-shrink-0"
            title="Remove this server from the list"
            @click="remove(device.deviceId)"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import SettingRow from '../SettingRow.vue'
import { desktop } from '../../../desktop'
import { useMultiDevice } from '../../../composables/useMultiDevice'

const { devices, refresh, loadSelf, isOnline, lastSeenLabel } = useMultiDevice()

const status = ref(null)
const saving = ref(false)
const error = ref('')
const nameDraft = ref('')

const serving = computed(() => status.value?.serving === true)

const peers = computed(() =>
  devices.value.filter((d) => d.deviceId !== status.value?.deviceId),
)

function deviceTags(device) {
  if (!device) return []
  const out = []
  if (device.channel && device.channel !== 'production') out.push(device.channel)
  if (device.sandbox && device.sandbox !== 'default') out.push(device.sandbox)
  return out
}

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

async function remove(deviceId) {
  try {
    await desktop.mdForgetDevice(deviceId)
    await refresh()
  } catch (e) {
    console.warn('[MultiDevice] remove failed:', e)
  }
}

onMounted(async () => {
  await loadStatus()
  await refresh()
})
</script>
