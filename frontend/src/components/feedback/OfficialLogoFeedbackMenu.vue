<template>
  <div class="py-1 relative">
    <button
      @click="openFeedback"
      class="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5 transition-colors"
      :class="coachmarkVisible
        ? 'bg-blue-500/15 text-blue-500'
        : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'"
    >
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 0 1 1.037-.443 48.282 48.282 0 0 0 5.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
      </svg>
      <span>Feedback...</span>
    </button>
    <div
      v-if="coachmarkVisible"
      class="absolute right-[calc(100%+0.75rem)] top-1/2 -translate-y-1/2 w-[230px] bg-surface border border-blue-500/50 rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] px-3.5 py-3 z-[10001]"
    >
      <p class="text-xs text-content leading-relaxed">Tell us what you think - it goes straight to the team.</p>
      <div class="absolute left-full top-1/2 -translate-y-1/2 border-8 border-transparent border-l-blue-500/50"></div>
    </div>
  </div>

  <div class="border-t border-edge-subtle"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useFeedback } from '../../composables/useFeedback'
import { makeGlobalKey } from '../../utils/storageKeys'

const emit = defineEmits(['close-menu', 'ensure-menu-open'])
const route = useRoute()
const { state: feedbackState, openMenuFeedback, markCoachmarkShown } = useFeedback()
const coachmarkVisible = ref(false)

function maybeShowCoachmark() {
  if (coachmarkVisible.value || feedbackState.coachmarkShown) return
  if (!localStorage.getItem(makeGlobalKey('onboarding_completed'))) return
  if (route.name === 'onboarding') return
  coachmarkVisible.value = true
  emit('ensure-menu-open')
  markCoachmarkShown()
}

function handleSettingsLoadedForCoachmark() {
  setTimeout(() => {
    if (feedbackState.loaded) maybeShowCoachmark()
  }, 600)
}

function openFeedback() {
  const fromCoachmark = coachmarkVisible.value
  coachmarkVisible.value = false
  emit('close-menu')
  openMenuFeedback(fromCoachmark ? 'coachmark' : 'menu')
}

onMounted(() => {
  window.addEventListener('settings-loaded', handleSettingsLoadedForCoachmark)
  handleSettingsLoadedForCoachmark()
})

onBeforeUnmount(() => {
  window.removeEventListener('settings-loaded', handleSettingsLoadedForCoachmark)
})
</script>
