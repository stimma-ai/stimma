<template>
  <section class="mt-9">
    <h3 class="text-xs font-semibold text-content-secondary">Multi-device</h3>

    <div class="mt-2">
      <SettingRow label="Serve this computer">
        <template #description>
          Other computers signed into your account can browse and create here.
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
      <div class="flex items-center justify-between gap-4 py-1.5 border-b border-edge-subtle">
        <span class="text-xs text-content-tertiary flex-shrink-0">This computer</span>
        <input
          v-model="nameDraft"
          class="text-xs font-mono text-content text-right bg-transparent border border-transparent rounded px-1.5 py-0.5 min-w-0 max-w-[240px] focus:outline-none focus:border-edge hover:border-edge-subtle transition-colors"
          :placeholder="status?.deviceName || 'This computer'"
          @blur="commitName"
          @keydown.enter="$event.target.blur()"
          @keydown.esc="nameDraft = status?.deviceName || ''"
        />
      </div>

      <div
        v-if="qualifier"
        class="flex items-baseline justify-between gap-4 py-1.5 border-b border-edge-subtle"
      >
        <span class="text-xs text-content-tertiary flex-shrink-0">Install</span>
        <span class="text-xs font-mono text-content-secondary text-right select-text">{{ qualifier }}</span>
      </div>
      <div class="flex items-baseline justify-between gap-4 py-1.5">
        <span class="text-xs text-content-tertiary flex-shrink-0">Reachable at</span>
        <span class="text-xs font-mono text-content text-right min-w-0 truncate select-text">{{ routeSummary }}</span>
      </div>
    </div>

    <!-- Connected devices ledger -->
    <div v-if="peers.length" class="mt-6">
      <div class="text-xs font-semibold text-content-secondary">Connected devices</div>
      <div class="mt-2">
        <div
          v-for="(device, i) in peers"
          :key="device.deviceId"
          class="flex items-center justify-between gap-4 py-2"
          :class="i < peers.length - 1 ? 'border-b border-edge-subtle' : ''"
        >
          <div class="min-w-0">
            <div class="text-[13px] text-content truncate">{{ device.name }}</div>
            <div class="text-[11.5px] text-content-tertiary">
              {{ [device.platform, deviceQualifier(device), lastSeen(device.lastSeenAt)].filter(Boolean).join(' · ') }}
            </div>
          </div>
          <!-- Housekeeping only: the row comes back if that device connects
               again. Trust is the account, so this is not a revoke. -->
          <button
            class="p-1.5 rounded text-content-muted hover:text-content hover:bg-overlay-subtle transition-colors cursor-pointer"
            title="Forget this device"
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
import { getApiBase } from '../../../apiConfig'
import { useMultiDevice } from '../../../composables/useMultiDevice'

const { devices, refresh } = useMultiDevice()

const status = ref(null)
const saving = ref(false)
const error = ref('')
const nameDraft = ref('')

const serving = computed(() => status.value?.serving === true)

const peers = computed(() =>
  devices.value.filter((d) => d.deviceId !== status.value?.deviceId),
)

/** Non-default channel/sandbox for THIS install. Empty when both default. */
const qualifier = computed(() => deviceQualifier(status.value))

function deviceQualifier(device) {
  if (!device) return ''
  const parts = []
  if (device.channel && device.channel !== 'production') parts.push(device.channel)
  if (device.sandbox && device.sandbox !== 'default') parts.push(device.sandbox)
  return parts.join(' · ')
}

const routeSummary = computed(() => {
  const routes = status.value?.routes || []
  if (!routes.length) return status.value?.serving ? '—' : 'not serving'
  const kinds = []
  if (routes.some((r) => r.kind === 'lan')) kinds.push('local network')
  if (routes.some((r) => r.kind === 'tailscale')) kinds.push('Tailscale')
  return kinds.join(' · ')
})

function lastSeen(iso) {
  if (!iso) return 'never seen'
  const delta = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(delta / 60000)
  if (minutes < 2) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

async function loadStatus() {
  try {
    const response = await fetch(`${getApiBase()}/multi-device/status`)
    if (response.ok) {
      status.value = await response.json()
      nameDraft.value = status.value.deviceName || ''
    }
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
    const response = await fetch(`${getApiBase()}/multi-device/name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (!response.ok) throw new Error(`rename failed (${response.status})`)
    status.value = await response.json()
    nameDraft.value = status.value.deviceName || ''
    await refresh()
  } catch (e) {
    error.value = String(e.message || e)
    nameDraft.value = status.value?.deviceName || ''
  }
}

async function toggleServing() {
  saving.value = true
  error.value = ''
  try {
    const response = await fetch(`${getApiBase()}/multi-device/serving`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !serving.value }),
    })
    if (!response.ok) throw new Error(`serving toggle failed (${response.status})`)
    status.value = await response.json()
    await refresh()
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    saving.value = false
  }
}

async function remove(deviceId) {
  try {
    await fetch(`${getApiBase()}/multi-device/devices/${deviceId}`, { method: 'DELETE' })
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
