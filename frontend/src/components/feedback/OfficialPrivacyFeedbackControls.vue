<template>
  <div
    v-for="row in feedbackConsentRows"
    :key="row.subject"
    class="flex items-center justify-between gap-3"
  >
    <div class="min-w-0">
      <div class="text-xs font-medium text-content">{{ row.label }}</div>
      <div class="text-[11px] text-content-muted mt-0.5">{{ row.description }}</div>
    </div>
    <div class="flex items-center gap-1 p-1 bg-surface rounded-lg border border-edge flex-shrink-0">
      <button
        v-for="option in ['ask', 'always', 'never']"
        :key="option"
        @click="setFeedbackConsent(row.subject, option)"
        class="px-2.5 h-7 rounded-md text-xs capitalize transition-all border"
        :class="row.value === option
          ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
          : 'bg-transparent border-transparent text-content-tertiary hover:text-content'"
      >{{ option }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useFeedback } from '../../composables/useFeedback'

const { state: feedbackConsentState, setConsent, loadState: loadFeedbackState } = useFeedback()

onMounted(() => {
  if (!feedbackConsentState.loaded) loadFeedbackState()
})

const feedbackConsentRows = computed(() => [
  {
    subject: 'thumbs',
    label: 'Thumbs ratings',
    description: 'Ask prompts before sending; Always sends ratings immediately.',
    value: feedbackConsentState.thumbsConsent,
  },
  {
    subject: 'crash',
    label: 'Crash reports',
    description: 'Ask keeps reports local until you decide; Always sends future reports without another prompt.',
    value: feedbackConsentState.crashConsent,
  },
])

async function setFeedbackConsent(subject, value) {
  try {
    await setConsent(subject, value)
  } catch (err) {
    console.error('Failed to update feedback consent:', err)
  }
}
</script>
