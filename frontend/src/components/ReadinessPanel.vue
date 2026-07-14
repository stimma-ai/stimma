<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="shouldShowPanel"
        data-testid="readiness-panel"
        class="fixed inset-0 z-[10005] flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="handleDismiss"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden relative">
          <!-- Close -->
          <button
            @click="handleDismiss"
            class="absolute top-3.5 right-3.5 z-10 p-1 rounded text-content-tertiary hover:text-content hover:bg-overlay-hover transition-colors"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>

          <!-- Readiness hero -->
          <div
            class="px-6 pt-8 text-center"
            :class="privacyLockdownActive ? 'pb-2' : 'pb-6 border-b border-edge readiness-hero'"
          >
            <h3 class="text-lg font-semibold text-content tracking-tight">{{ headline }}</h3>
            <p v-if="!privacyLockdownActive" class="mt-1.5 mx-auto max-w-[350px] text-sm text-content-secondary leading-relaxed">
              {{ heroText }}
            </p>
            <button
              v-if="!privacyLockdownActive"
              @click="handleCloudCta"
              :disabled="connecting"
              class="mt-4 px-5 py-2.5 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-white rounded-lg text-sm font-semibold transition-all disabled:opacity-60"
            >
              {{ connecting ? 'Connecting…' : (user ? 'Add balance' : 'Sign in to Stimma') }}
            </button>
            <p v-if="!privacyLockdownActive" class="mt-2.5 text-xs text-content-muted">Nothing to install or configure.</p>
            <p v-if="!privacyLockdownActive && connectError" class="text-xs text-red-500 mt-2">{{ connectError }}</p>
          </div>

          <!-- Bring your own AI -->
          <div class="px-6 pt-4 pb-4">
            <h4 v-if="!privacyLockdownActive" class="text-center text-[13px] font-semibold text-content-secondary">Or, bring your own AI</h4>
            <div class="flex flex-col" :class="{ 'mt-2.5': !privacyLockdownActive }">
              <div class="flex items-center gap-3 py-2.5 px-2 -mx-2">
                <span
                  class="w-5 h-5 flex-none rounded-full border flex items-center justify-center text-[11px] font-semibold"
                  :class="missingAgentLlm ? 'border-edge-strong text-content-tertiary' : 'border-green-500/40 text-green-400'"
                >{{ missingAgentLlm ? '1' : '✓' }}</span>
                <span class="flex-1 text-sm font-medium" :class="missingAgentLlm ? 'text-content' : 'text-content-tertiary'">Connect a local LLM</span>
                <button
                  v-if="missingAgentLlm"
                  @click="openSettingsSection('ai-services')"
                  class="text-[12.5px] text-content-tertiary hover:text-content transition-colors whitespace-nowrap"
                >Settings → Advanced</button>
                <span v-else class="text-xs text-green-400">Connected</span>
              </div>
              <div class="flex items-center gap-3 py-2.5 px-2 -mx-2">
                <span
                  class="w-5 h-5 flex-none rounded-full border flex items-center justify-center text-[11px] font-semibold"
                  :class="missingGeneration ? 'border-edge-strong text-content-tertiary' : 'border-green-500/40 text-green-400'"
                >{{ missingGeneration ? (missingAgentLlm ? '2' : '1') : '✓' }}</span>
                <span class="flex-1 text-sm font-medium" :class="missingGeneration ? 'text-content' : 'text-content-tertiary'">Connect generation tools</span>
                <button
                  v-if="missingGeneration"
                  @click="openSettingsSection('tools')"
                  class="text-[12.5px] text-content-tertiary hover:text-content transition-colors whitespace-nowrap"
                >Settings → Tools</button>
                <span v-else class="text-xs text-green-400">Connected</span>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 border-t border-edge flex items-center justify-between">
            <label class="flex items-center gap-2 text-sm text-content-tertiary cursor-pointer select-none">
              <input type="checkbox" :checked="dontShowAgain" @change="handleDontShowToggle" class="rounded border-edge" />
              Don't show this again
            </label>
            <button
              data-testid="readiness-dismiss"
              @click="handleDismiss"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium text-sm transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useReadiness } from '../composables/useReadiness'
import { useAuth } from '../composables/useAuth'
import { useCloudAccount } from '../composables/useCloudAccount'
import { usePrivacyLockdown } from '../composables/usePrivacyLockdown'
import { isTauri } from '../apiConfig'

const { readiness, shouldShowPanel, dontShowAgain, dismissPanel, setDontShowAgain } = useReadiness()
const { user, signInWithBrowser } = useAuth()
const { cloudBaseUrl, ensureCloudBaseUrl } = useCloudAccount()
const { privacyLockdownActive } = usePrivacyLockdown()

const connecting = ref(false)
const connectError = ref('')

const missingAgentLlm = computed(() => !!readiness.value?.missing?.includes('agent_llm'))
const missingGeneration = computed(() => !!readiness.value?.missing?.includes('generation'))

const headline = computed(() => {
  if (privacyLockdownActive.value) return 'Bring your own AI'
  if (missingAgentLlm.value && missingGeneration.value) return 'Connect AI to start creating'
  return 'One step left'
})

const heroText = computed(() => {
  if (user.value) {
    if (missingAgentLlm.value && missingGeneration.value) return 'Add balance to unlock the agent and generation tools, hosted.'
    if (missingAgentLlm.value) return 'Add balance to give the agent a hosted model.'
    return 'Add balance to unlock hosted generation tools.'
  }
  if (missingAgentLlm.value && missingGeneration.value) return 'One sign-in sets up everything — the agent and generation tools, hosted.'
  if (missingAgentLlm.value) return 'One sign-in gives the agent a hosted model.'
  return 'One sign-in adds hosted generation tools.'
})

function handleDismiss() {
  dismissPanel()
}

function handleDontShowToggle(e) {
  setDontShowAgain(e.target.checked)
}

function openSettingsSection(section) {
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

async function handleCloudCta() {
  connectError.value = ''
  if (user.value) {
    // Already signed in with no balance — go straight to the dashboard to
    // add balance. No prices in-app; the web owns commerce.
    await ensureCloudBaseUrl()
    await openUrl(cloudBaseUrl.value + '/link/addcredits')
    return
  }
  connecting.value = true
  try {
    await signInWithBrowser()
  } catch (error) {
    connectError.value = error.message || 'Connection failed'
  } finally {
    connecting.value = false
  }
}
</script>

<style scoped>
/* Radial washes aren't expressible with Tailwind utilities. */
.readiness-hero {
  background:
    radial-gradient(ellipse at 50% -40%, rgba(6, 182, 212, 0.18), transparent 65%),
    radial-gradient(ellipse at 100% 0%, rgba(99, 102, 241, 0.12), transparent 55%);
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .bg-surface,
.modal-leave-active .bg-surface {
  transition: transform 0.15s ease;
}

.modal-enter-from .bg-surface,
.modal-leave-to .bg-surface {
  transform: scale(0.95);
}
</style>
