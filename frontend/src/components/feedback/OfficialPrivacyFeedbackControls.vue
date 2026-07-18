<template>
  <div
    v-for="row in feedbackConsentRows"
    :key="row.subject"
    class="flex items-center justify-between gap-6"
  >
    <div class="min-w-0 max-w-md">
      <div class="text-xs font-medium text-content">{{ row.label }}</div>
      <div class="text-[11px] text-content-muted mt-0.5">{{ row.description }}</div>
    </div>
    <div class="flex flex-shrink-0 items-center gap-0.5">
      <button
        v-for="option in ['ask', 'always', 'never']"
        :key="option"
        @click="setFeedbackConsent(row.subject, option)"
        class="rounded-md px-2.5 py-1 text-xs capitalize transition-colors"
        :class="row.value === option
          ? 'bg-accent/15 text-accent'
          : 'text-content-tertiary hover:text-content'"
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
