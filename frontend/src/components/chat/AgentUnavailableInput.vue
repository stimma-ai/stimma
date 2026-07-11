<template>
  <div class="flex min-h-[154px] flex-col items-center justify-center px-6 py-7 text-center sm:px-8">
    <div class="text-sm font-semibold text-content">Agent unavailable</div>
    <p class="mt-1.5 text-sm leading-5 text-content-tertiary">
      <template v-if="privacyLockdownActive">
        Connect a local LLM to use the agent.
      </template>
      <template v-else>
        Connect Stimma Cloud or configure a local LLM to start chatting.
      </template>
    </p>

    <div class="mt-5 flex flex-wrap items-center justify-center gap-2.5">
      <button
        v-if="!privacyLockdownActive"
        type="button"
        @click="openSettings('account')"
        class="rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400"
      >
        Connect Stimma Cloud
      </button>
      <button
        type="button"
        @click="openSettings('ai-services')"
        class="rounded-lg border border-edge bg-transparent px-4 py-2 text-sm font-medium text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content"
      >
        Configure local LLM
      </button>
    </div>
  </div>
</template>

<script setup>
import { usePrivacyLockdown } from '../../composables/usePrivacyLockdown'

const { privacyLockdownActive } = usePrivacyLockdown()

function openSettings(section) {
  window.dispatchEvent(new CustomEvent('open-settings', { detail: section }))
}
</script>
