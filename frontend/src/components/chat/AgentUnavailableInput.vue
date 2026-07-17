<template>
  <div class="flex min-h-[154px] flex-col items-center justify-center px-6 py-7 text-center sm:px-8">
    <div class="text-sm font-semibold text-content">Stimma needs AI to work</div>
    <p class="mt-1.5 text-sm leading-5 text-content-tertiary">
      <template v-if="unavailableState === 'privacy'">
        You need a local chat model to use the agent.
      </template>
      <template v-else-if="unavailableState === 'no-balance'">
        You're out of Stimma credits.
      </template>
      <template v-else>
        You need a chat model to use the agent.
      </template>
    </p>

    <div class="mt-5 flex flex-wrap items-center justify-center gap-2.5">
      <button
        v-if="unavailableState === 'no-balance'"
        type="button"
        :disabled="addBalancePending"
        @click="handleAddBalance"
        class="rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400"
      >
        {{ addBalancePending ? 'Opening…' : 'Add credits' }}
      </button>
      <button
        type="button"
        @click="openSettings('ai-services')"
        class="rounded-lg border border-edge bg-transparent px-4 py-2 text-sm font-medium text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content"
      >
        Configure Chat Models
      </button>
    </div>
    <RedeemCodeLink v-if="unavailableState === 'no-balance'" class="mt-3" />
    <p v-if="actionError" class="mt-2 text-xs text-red-500">{{ actionError }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { isTauri } from '../../apiConfig'
import { useAuth } from '../../composables/useAuth'
import { useAvailableModels } from '../../composables/useAvailableModels'
import { useCloudAccount } from '../../composables/useCloudAccount'
import { usePrivacyLockdown } from '../../composables/usePrivacyLockdown'
import { resolveAgentUnavailableState } from '../../utils/agentUnavailableState'
import RedeemCodeLink from '../RedeemCodeLink.vue'

const { privacyLockdownActive } = usePrivacyLockdown()
const { isAuthenticated } = useAuth()
const { cloudStatus } = useAvailableModels()
const { cloudBaseUrl, cloudUser, ensureCloudBaseUrl } = useCloudAccount()
const addBalancePending = ref(false)
const actionError = ref('')

const unavailableState = computed(() => resolveAgentUnavailableState({
  privacyLockdownActive: privacyLockdownActive.value,
  isAuthenticated: isAuthenticated.value,
  cloudCredits: cloudUser.value?.credits ?? null,
  cloudStatus: cloudStatus.value,
}))

function openSettings(section) {
  window.dispatchEvent(new CustomEvent('open-settings', { detail: section }))
}

async function openUrl(url) {
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } else {
    window.open(url, '_blank')
  }
}

async function handleAddBalance() {
  addBalancePending.value = true
  actionError.value = ''
  try {
    await ensureCloudBaseUrl()
    await openUrl(`${cloudBaseUrl.value}/link/addcredits`)
  } catch (error) {
    actionError.value = error?.message || 'Could not open Stimma.'
  } finally {
    addBalancePending.value = false
  }
}
</script>
