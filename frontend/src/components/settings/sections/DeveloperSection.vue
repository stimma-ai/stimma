<template>
  <div>
    <div class="mb-3">
      <h3 class="text-base font-medium text-content">Developer</h3>
      <p class="mt-1 text-xs text-content-tertiary">Debug tools and developer options</p>
    </div>

    <div class="mt-6 max-w-[680px]">
      <SettingRow label="Developer Mode" description="Show debug tools and additional developer options throughout the UI">
        <button
          @click="toggleDeveloperMode"
          :class="[
            'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface',
            localDevMode ? 'bg-accent' : 'bg-surface-hover'
          ]"
        >
          <span
            :class="[
              'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
              localDevMode ? 'translate-x-5' : 'translate-x-0'
            ]"
          />
        </button>
      </SettingRow>

      <!-- Dev-only tools -->
      <template v-if="localDevMode">
        <!-- Hide Prices Toggle (for marketing screenshots) -->
        <SettingRow label="Hide Prices" description="Hide all price/cost display throughout the UI">
          <button
            @click="toggleHidePrices"
            :class="[
              'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface',
              hidePricesRef ? 'bg-accent' : 'bg-surface-hover'
            ]"
          >
            <span
              :class="[
                'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                hidePricesRef ? 'translate-x-5' : 'translate-x-0'
              ]"
            />
          </button>
        </SettingRow>

        <!-- Hide Account Toggle (for marketing screenshots) -->
        <SettingRow label="Hide Account" description="Show the signed-out sidebar footer instead of the account chip">
          <button
            @click="toggleHideAccount"
            :class="[
              'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface',
              hideAccountRef ? 'bg-accent' : 'bg-surface-hover'
            ]"
          >
            <span
              :class="[
                'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                hideAccountRef ? 'translate-x-5' : 'translate-x-0'
              ]"
            />
          </button>
        </SettingRow>

        <!-- Force FFmpeg Missing Toggle (for taking screenshots of the warning UI) -->
        <SettingRow label="Force FFmpeg Missing" description="Pretend FFmpeg isn't installed, to preview the missing-FFmpeg warning">
          <button
            @click="toggleForceFfmpegMissing"
            :class="[
              'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface',
              localForceFfmpegMissing ? 'bg-accent' : 'bg-surface-hover'
            ]"
          >
            <span
              :class="[
                'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                localForceFfmpegMissing ? 'translate-x-5' : 'translate-x-0'
              ]"
            />
          </button>
        </SettingRow>

        <SettingRow label="Request Metrics" description="Inspect endpoint latency percentiles for recent requests">
          <Button variant="ghost" size="sm" @click="openRequestMetricsModal">Open Request Metrics</Button>
        </SettingRow>

        <SettingRow label="Reset Welcome Screen" description="Clear the welcome screen completion flag and show it again">
          <Button variant="ghost" size="sm" @click="resetOnboarding">Show Welcome Screen</Button>
        </SettingRow>

        <SettingRow label="Run Setup Wizard" description="Clear the shown-once flag and open the AI setup wizard">
          <Button variant="ghost" size="sm" @click="runSetupWizard">Run Wizard</Button>
        </SettingRow>

        <SettingRow label="Preview What's New" description="Show the What's New pill with the latest published release notes">
          <Button variant="ghost" size="sm" @click="previewWhatsNew">Show Pill</Button>
        </SettingRow>

        <SettingRow label="Replay First-Run Tour" description="Run the sidebar coachmark tour again (Chats, Tools, Feedback)">
          <Button variant="ghost" size="sm" @click="replayTour">Replay Tour</Button>
        </SettingRow>

        <SettingRow v-if="isTauri()" label="Set Window Size to 1440×900" description="Resize the window to a logical 1440×900">
          <Button variant="ghost" size="sm" @click="setWindowSize1440x900">Set 1440×900</Button>
        </SettingRow>

        <SettingRow label="Database maintenance" description="Analyze and safely clean historical SQLite foreign-key debris for the current profile">
          <Button variant="ghost" size="sm" @click="showDatabaseCleanupModal = true">Open maintenance</Button>
        </SettingRow>
      </template>
    </div>

    <DatabaseCleanupModal
      :show="showDatabaseCleanupModal"
      @close="showDatabaseCleanupModal = false"
    />

    <!-- Request Metrics Modal -->
    <div v-if="showRequestMetricsModal" class="fixed inset-0 z-modal bg-overlay-backdrop backdrop-blur-sm p-4 flex flex-col" @click.self="closeRequestMetricsModal">
      <div class="w-full h-full bg-surface border border-edge rounded-lg shadow-2xl flex flex-col overflow-hidden">
        <div class="px-5 py-4 border-b border-edge flex items-center justify-between">
          <div>
            <h3 class="text-base font-semibold text-content">Request Latency Metrics</h3>
            <p class="text-xs text-content-tertiary mt-0.5">
              {{ metricsSummary }}
            </p>
          </div>
          <button
            @click="closeRequestMetricsModal"
            class="w-8 h-8 flex items-center justify-center text-content-tertiary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="px-5 py-3 border-b border-edge flex flex-wrap items-center gap-2">
          <input
            v-model="metricsSearch"
            type="text"
            placeholder="Filter by method or path"
            class="w-[320px] max-w-full bg-surface-raised border border-edge rounded px-2.5 py-1.5 text-xs text-content focus:outline-none focus:border-accent"
          />
          <select
            v-model="metricsSortBy"
            @change="loadRequestMetrics"
            class="bg-surface-raised border border-edge rounded px-2 py-1.5 text-xs text-content focus:outline-none focus:border-accent"
          >
            <option value="p95_ms">Sort: p95</option>
            <option value="p99_ms">Sort: p99</option>
            <option value="avg_ms">Sort: avg</option>
            <option value="count">Sort: count</option>
            <option value="max_ms">Sort: max</option>
          </select>
          <button
            @click="loadRequestMetrics"
            :disabled="metricsLoading"
            class="px-3 py-1.5 text-xs font-medium rounded border bg-surface-raised border-edge text-content-secondary hover:border-edge hover:bg-surface transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ metricsLoading ? 'Loading...' : 'Refresh' }}
          </button>
          <button
            @click="toggleAutoRefresh"
            class="px-3 py-1.5 text-xs font-medium rounded border transition-all"
            :class="metricsAutoRefresh ? 'bg-accent/15 border-accent/50 text-accent' : 'bg-surface-raised border-edge text-content-secondary hover:border-edge hover:bg-surface'"
          >
            Auto-refresh {{ metricsAutoRefresh ? 'On' : 'Off' }}
          </button>
          <button
            @click="showResetConfirm = true"
            class="ml-auto px-3 py-1.5 text-xs font-medium rounded border bg-red-500/15 border-red-500/50 text-red-500 hover:bg-red-500/20 transition-all"
          >
            Reset Stats
          </button>
        </div>

        <div v-if="showResetConfirm" class="px-5 py-3 border-b border-edge bg-red-500/10 flex items-center gap-2">
          <span class="text-xs text-red-500">Clear all in-memory request metric windows?</span>
          <button
            @click="confirmResetMetrics"
            :disabled="metricsResetting"
            class="px-2.5 py-1 text-xs font-medium rounded border bg-red-500/15 border-red-500/50 text-red-500 hover:bg-red-500/20 disabled:opacity-50"
          >
            {{ metricsResetting ? 'Resetting...' : 'Confirm Reset' }}
          </button>
          <button
            @click="showResetConfirm = false"
            class="px-2.5 py-1 text-xs font-medium rounded border bg-surface-raised border-edge text-content-secondary hover:bg-surface"
          >
            Cancel
          </button>
        </div>

        <div class="flex-1 overflow-auto">
          <div v-if="metricsError" class="p-4 text-sm text-red-500">
            {{ metricsError }}
          </div>
          <table v-else class="w-full text-xs table-fixed">
            <thead class="sticky top-0 bg-surface border-b border-edge">
              <tr class="text-content-tertiary">
                <th class="text-left px-3 py-2 font-medium">Method</th>
                <th class="text-left px-3 py-2 font-medium">Path</th>
                <th class="text-right px-3 py-2 font-medium">Count</th>
                <th class="text-right px-3 py-2 font-medium">Avg</th>
                <th class="text-right px-3 py-2 font-medium">P50</th>
                <th class="text-right px-3 py-2 font-medium">P90</th>
                <th class="text-right px-3 py-2 font-medium">P95</th>
                <th class="text-right px-3 py-2 font-medium">P99</th>
                <th class="text-right px-3 py-2 font-medium">Max</th>
                <th class="text-right px-3 py-2 font-medium">5xx</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in filteredMetricRows" :key="`${row.method} ${row.path}`" class="border-b border-edge/60">
                <td class="px-3 py-2 text-content">{{ row.method }}</td>
                <td class="px-3 py-2 text-content-secondary font-mono truncate max-w-[500px]" :title="row.path">{{ row.path }}</td>
                <td class="px-3 py-2 text-right text-content">{{ row.count }}</td>
                <td class="px-3 py-2 text-right text-content">{{ formatMs(row.avg_ms) }}</td>
                <td class="px-3 py-2 text-right text-content">{{ formatMs(row.p50_ms) }}</td>
                <td class="px-3 py-2 text-right text-content">{{ formatMs(row.p90_ms) }}</td>
                <td class="px-3 py-2 text-right text-content">{{ formatMs(row.p95_ms) }}</td>
                <td class="px-3 py-2 text-right text-content">{{ formatMs(row.p99_ms) }}</td>
                <td class="px-3 py-2 text-right text-content">{{ formatMs(row.max_ms) }}</td>
                <td class="px-3 py-2 text-right">
                  <span
                    class="inline-flex items-center justify-center min-w-[24px] px-1.5 py-0.5 rounded border"
                    :class="row.status_5xx > 0 ? 'bg-red-500/15 border-red-500/50 text-red-500' : 'border-edge-subtle bg-overlay-light text-content-tertiary'"
                  >
                    {{ row.status_5xx }}
                  </span>
                </td>
              </tr>
              <tr v-if="!metricsLoading && filteredMetricRows.length === 0">
                <td colspan="10" class="px-3 py-6 text-center text-content-muted">No matching endpoints</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsApi } from '../../../composables/useSettingsApi'
import { useReadiness } from '../../../composables/useReadiness'
import { useTour } from '../../../composables/useTour'
import { useReleaseNotes } from '../../../composables/useReleaseNotes'
import { makeGlobalKey } from '../../../utils/storageKeys'
import { hideAccountRef, hidePricesRef, setHideAccount, setHidePrices } from '../../../appConfig'
import { isTauri } from '../../../apiConfig'
import DatabaseCleanupModal from '../DatabaseCleanupModal.vue'
import SettingRow from '../SettingRow.vue'
import Button from '../../ui/Button.vue'

const props = defineProps({
  developerMode: {
    type: Boolean,
    default: false
  },
  debugForceFfmpegMissing: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update-developer-mode', 'update-debug-force-ffmpeg-missing', 'close-settings'])

const localDevMode = ref(false)
const localForceFfmpegMissing = ref(false)
const { fetchRequestMetrics, resetRequestMetrics } = useSettingsApi()

const showRequestMetricsModal = ref(false)
const showDatabaseCleanupModal = ref(false)
const metricsLoading = ref(false)
const metricsResetting = ref(false)
const metricsError = ref('')
const metricsRows = ref([])
const metricsSummaryState = ref(null)
const metricsSearch = ref('')
const metricsSortBy = ref('p95_ms')
const metricsAutoRefresh = ref(true)
const showResetConfirm = ref(false)
let metricsTimer = null

watch(() => props.developerMode, (newValue) => {
  localDevMode.value = newValue
}, { immediate: true })

watch(() => props.debugForceFfmpegMissing, (newValue) => {
  localForceFfmpegMissing.value = newValue
}, { immediate: true })

function toggleDeveloperMode() {
  const newValue = !localDevMode.value
  localDevMode.value = newValue
  emit('update-developer-mode', newValue)
}

function toggleForceFfmpegMissing() {
  const newValue = !localForceFfmpegMissing.value
  localForceFfmpegMissing.value = newValue
  emit('update-debug-force-ffmpeg-missing', newValue)
}

function toggleHidePrices() {
  setHidePrices(!hidePricesRef.value)
}

function toggleHideAccount() {
  setHideAccount(!hideAccountRef.value)
}

async function setWindowSize1440x900() {
  const { getCurrentWindow, LogicalSize } = await import('@tauri-apps/api/window')
  await getCurrentWindow().setSize(new LogicalSize(1440, 900))
}

const router = useRouter()
function resetOnboarding() {
  // Close settings first so finishing onboarding lands in the app, not settings.
  emit('close-settings')
  localStorage.removeItem(makeGlobalKey('onboarding_completed'))
  router.push({ name: 'onboarding' })
}

function runSetupWizard() {
  // The wizard renders below the settings modal, so close settings first.
  emit('close-settings')
  useReadiness().relaunchWizard()
}

async function previewWhatsNew() {
  // Close settings so the top-bar pill (and its peek animation) is visible.
  const shown = await useReleaseNotes().devPreviewWhatsNew()
  if (shown) emit('close-settings')
}

function replayTour() {
  // The tour anchors to the sidebar, so close settings first. The tour's
  // trigger only fires on the home route — go there too.
  emit('close-settings')
  router.push({ name: 'home' })
  useTour().relaunchTour()
}

const filteredMetricRows = computed(() => {
  const q = metricsSearch.value.trim().toLowerCase()
  if (!q) return metricsRows.value
  return metricsRows.value.filter(row =>
    row.method.toLowerCase().includes(q) || row.path.toLowerCase().includes(q)
  )
})

const metricsSummary = computed(() => {
  const data = metricsSummaryState.value
  if (!data) return 'No metrics collected yet'
  const generatedAt = data.generated_at ? new Date(data.generated_at).toLocaleTimeString() : 'n/a'
  return `${data.endpoint_count} endpoints · ${data.total_requests_in_window} requests in window · size ${data.window_size} · updated ${generatedAt}`
})

function formatMs(value) {
  if (typeof value !== 'number') return '-'
  return `${value.toFixed(1)}ms`
}

async function loadRequestMetrics() {
  metricsLoading.value = true
  metricsError.value = ''
  try {
    const data = await fetchRequestMetrics({
      sort_by: metricsSortBy.value,
      limit: 500,
    })
    metricsRows.value = data.endpoints || []
    metricsSummaryState.value = data
  } catch (err) {
    console.error('Failed to load request metrics:', err)
    metricsError.value = err.response?.data?.detail || err.message || 'Failed to load metrics'
  } finally {
    metricsLoading.value = false
  }
}

function openRequestMetricsModal() {
  showRequestMetricsModal.value = true
  showResetConfirm.value = false
  loadRequestMetrics()
  syncMetricsTimer()
}

function closeRequestMetricsModal() {
  showRequestMetricsModal.value = false
  showResetConfirm.value = false
  syncMetricsTimer()
}

function toggleAutoRefresh() {
  metricsAutoRefresh.value = !metricsAutoRefresh.value
  syncMetricsTimer()
}

function clearMetricsTimer() {
  if (metricsTimer) {
    clearInterval(metricsTimer)
    metricsTimer = null
  }
}

function syncMetricsTimer() {
  clearMetricsTimer()
  if (showRequestMetricsModal.value && metricsAutoRefresh.value) {
    metricsTimer = setInterval(() => {
      loadRequestMetrics()
    }, 5000)
  }
}

async function confirmResetMetrics() {
  metricsResetting.value = true
  try {
    await resetRequestMetrics()
    showResetConfirm.value = false
    await loadRequestMetrics()
  } catch (err) {
    console.error('Failed to reset request metrics:', err)
    metricsError.value = err.response?.data?.detail || err.message || 'Failed to reset metrics'
  } finally {
    metricsResetting.value = false
  }
}

watch(localDevMode, (enabled) => {
  if (!enabled) showDatabaseCleanupModal.value = false
  if (!enabled && showRequestMetricsModal.value) {
    closeRequestMetricsModal()
  }
})

onUnmounted(() => {
  clearMetricsTimer()
})
</script>
