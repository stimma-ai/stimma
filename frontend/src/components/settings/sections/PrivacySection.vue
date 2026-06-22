<template>
  <div>
    <div class="flex items-center gap-3 mb-4">
      <h3 class="text-base font-medium text-content">Privacy</h3>
      <div class="flex items-center gap-1.5 text-xs text-blue-500 bg-blue-500/10 border border-blue-500/30 rounded-full px-2.5 py-1">
        <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 21.75c5.176-1.333 9-6.03 9-11.623 0-1.31-.21-2.57-.598-3.75A11.959 11.959 0 0 1 12 3.09a11.959 11.959 0 0 1-8.402 3.286A11.99 11.99 0 0 0 3 10.127c0 5.592 3.824 10.29 9 11.623Z" />
        </svg>
        <span>Applies to all profiles</span>
      </div>
    </div>

    <div class="space-y-4">
      <div v-if="isOfficial" class="p-4 bg-surface-raised/50 rounded-lg">
        <div class="flex items-center justify-between gap-4">
          <div class="flex-1 min-w-0">
            <h4 class="text-sm font-medium text-content">Usage Analytics</h4>
            <p class="text-xs text-content-tertiary mt-0.5 leading-relaxed">
              Help improve Stimma with first-party usage telemetry. Events do not include prompts, files, images, generation parameters, file names, or content you create. If you are signed in, telemetry can be associated with your Stimma Cloud account.
            </p>
            <p v-if="dntActive" class="text-xs text-content-tertiary mt-1">
              Environment override active: DO_NOT_TRACK=1 is set - usage telemetry is disabled regardless of this setting.
            </p>
          </div>
          <button
            @click="toggleTelemetry"
            :disabled="telemetrySaving"
            :aria-pressed="localTelemetryEnabled"
            class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-surface disabled:opacity-60"
            :class="localTelemetryEnabled ? 'bg-blue-600' : 'bg-surface-hover'"
          >
            <span
              class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
              :class="localTelemetryEnabled ? 'translate-x-5' : 'translate-x-0'"
            />
          </button>
        </div>
      </div>
      <div v-else class="p-4 bg-surface-raised/50 rounded-lg">
        <h4 class="text-sm font-medium text-content">Usage Analytics</h4>
        <p class="text-xs text-content-tertiary mt-0.5 leading-relaxed">
          Telemetry is disabled in source builds.
        </p>
      </div>

      <div v-if="isOfficial" class="p-4 bg-surface-raised/50 rounded-lg space-y-4">
        <div>
          <h4 class="text-sm font-medium text-content">Feedback Sharing</h4>
          <p class="text-xs text-content-tertiary mt-0.5 leading-relaxed">
            Thumbs ratings include the conversation. Crash reports include the error, stack trace, and recent log lines. "Ask" requires a prompt before sending; "Always" sends future items of that type without prompting.
          </p>
        </div>
        <PrivacyFeedbackControls />
      </div>
      <div v-else class="p-4 bg-surface-raised/50 rounded-lg">
        <h4 class="text-sm font-medium text-content">Feedback Sharing</h4>
        <p class="text-xs text-content-tertiary mt-0.5 leading-relaxed">
          Sharing feedback is disabled in source builds.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { getApiBase } from '../../../apiConfig'
import { isOfficialBuild } from '../../../distribution'
import PrivacyFeedbackControls from '@stimma/privacy-feedback-controls'

const props = defineProps({
  telemetryEnabled: {
    type: Boolean,
    default: false,
  },
  dntActive: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['telemetry-updated'])

const isOfficial = isOfficialBuild()
const localTelemetryEnabled = ref(true)
const telemetrySaving = ref(false)

watch(() => props.telemetryEnabled, (val) => {
  localTelemetryEnabled.value = val === true
}, { immediate: true })

async function toggleTelemetry() {
  const previous = localTelemetryEnabled.value
  const newValue = !previous
  localTelemetryEnabled.value = newValue
  telemetrySaving.value = true
  try {
    await fetch(`${getApiBase()}/settings/telemetry`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: newValue }),
    })
    emit('telemetry-updated', newValue)
  } catch (err) {
    localTelemetryEnabled.value = previous
    console.error('Failed to update telemetry setting:', err)
  } finally {
    telemetrySaving.value = false
  }
}

</script>
