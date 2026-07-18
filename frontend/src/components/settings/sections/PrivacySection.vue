<template>
  <div>
    <div class="mb-3">
      <div class="flex items-center gap-3">
        <h3 class="text-base font-medium text-content">Privacy</h3>
      </div>
    </div>

    <div class="mt-8 space-y-9">
      <div v-if="isOfficial" class="flex items-start justify-between gap-4">
        <div class="min-w-0 max-w-xl">
          <h4 class="text-sm font-medium text-content">Usage Analytics</h4>
          <p class="mt-1 text-xs leading-relaxed text-content-tertiary">
            Help improve Stimma with first-party usage telemetry. Events do not include prompts, files, images, generation parameters, file names, or content you create. If you are signed in, telemetry can be associated with your Stimma account.
          </p>
          <p v-if="privacyLockdownActive" class="mt-1 text-xs text-content-tertiary">
            Privacy Lockdown is active. Usage telemetry and Stimma services are disabled.
          </p>
        </div>
        <button
          @click="toggleTelemetry"
          :disabled="telemetrySaving || privacyLockdownActive"
          :aria-pressed="localTelemetryEnabled && !privacyLockdownActive"
          class="relative ml-4 inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface disabled:opacity-60"
          :class="localTelemetryEnabled && !privacyLockdownActive ? 'bg-blue-600' : 'bg-surface-hover'"
        >
          <span
            class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
            :class="localTelemetryEnabled && !privacyLockdownActive ? 'translate-x-5' : 'translate-x-0'"
          />
        </button>
      </div>
      <div v-else>
        <h4 class="text-sm font-medium text-content">Usage Analytics</h4>
        <p class="mt-0.5 text-xs leading-relaxed text-content-tertiary">
          Telemetry is disabled in source builds and cannot send events.
        </p>
      </div>

      <div v-if="isOfficial">
        <h4 class="text-sm font-medium text-content">Feedback Sharing</h4>
        <p class="mt-1 max-w-xl text-xs leading-relaxed text-content-tertiary">
          Thumbs ratings include the conversation. Crash reports include the error, stack trace, and recent log lines.
        </p>
        <div class="mt-6 space-y-5">
          <PrivacyFeedbackControls />
        </div>
      </div>
      <div v-else>
        <h4 class="text-sm font-medium text-content">Feedback Sharing</h4>
        <p class="mt-0.5 text-xs leading-relaxed text-content-tertiary">
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
  privacyLockdownActive: {
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
