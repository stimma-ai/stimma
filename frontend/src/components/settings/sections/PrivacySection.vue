<template>
  <div>
    <div class="mb-3">
      <div class="flex items-center gap-3">
        <h3 class="text-base font-medium text-content">Privacy</h3>
      </div>
    </div>

    <div class="mt-6 max-w-[680px]">
      <SettingRow v-if="isOfficial" label="Usage Analytics">
        <template #description>
          Help improve Stimma with first-party usage telemetry. Events do not include prompts, files, images, generation parameters, file names, or content you create. If you are signed in, telemetry can be associated with your Stimma account.
          <span v-if="privacyLockdownActive" class="block mt-1">Privacy Lockdown is active. Usage telemetry and Stimma services are disabled.</span>
        </template>
        <button
          @click="toggleTelemetry"
          :disabled="telemetrySaving || privacyLockdownActive"
          :aria-pressed="localTelemetryEnabled && !privacyLockdownActive"
          class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:opacity-60"
          :class="localTelemetryEnabled && !privacyLockdownActive ? 'bg-accent' : 'bg-surface-hover'"
        >
          <span
            class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
            :class="localTelemetryEnabled && !privacyLockdownActive ? 'translate-x-5' : 'translate-x-0'"
          />
        </button>
      </SettingRow>
      <div v-else class="py-2.5 border-b border-edge-subtle">
        <span class="block text-[13px] text-content">Usage Analytics</span>
        <span class="block text-[11.5px] text-content-tertiary mt-0.5">Telemetry is disabled in source builds and cannot send events.</span>
      </div>

      <div v-if="isOfficial" class="pt-4">
        <div class="text-xs font-semibold text-content-secondary">Feedback Sharing</div>
        <p class="mt-1 max-w-xl text-xs leading-relaxed text-content-tertiary">
          Thumbs ratings include the conversation. Crash reports include the error, stack trace, and recent log lines.
        </p>
        <div class="mt-4 space-y-5">
          <PrivacyFeedbackControls />
        </div>
      </div>
      <div v-else class="py-2.5">
        <span class="block text-[13px] text-content">Feedback Sharing</span>
        <span class="block text-[11.5px] text-content-tertiary mt-0.5">Sharing feedback is disabled in source builds.</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { getApiBase } from '../../../apiConfig'
import { isOfficialBuild } from '../../../distribution'
import PrivacyFeedbackControls from '@stimma/privacy-feedback-controls'
import SettingRow from '../SettingRow.vue'

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
