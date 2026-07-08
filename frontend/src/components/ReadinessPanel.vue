<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="shouldShowPanel"
        data-testid="readiness-panel"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="handleDismiss"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl max-w-lg w-full mx-4">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-edge flex items-center justify-between">
            <h3 class="text-lg font-semibold text-content">{{ headline }}</h3>
            <button
              @click="handleDismiss"
              class="p-1 rounded text-content-tertiary hover:text-content hover:bg-surface-hover transition-colors"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="px-6 py-5 flex flex-col gap-4">
            <p v-if="finishCheckoutNeeded" class="text-sm text-content-secondary">
              Checkout wasn't completed.
            </p>

            <!-- Stimma Cloud path -->
            <div class="rounded-lg border border-edge-strong bg-surface-raised p-4">
              <h4 class="text-sm font-semibold text-content mb-1.5">
                <span class="stimma-cloud-text">Stimma Cloud</span>
              </h4>
              <p class="text-sm text-content-tertiary leading-relaxed mb-3">
                One sign-in for {{ cloudCoversText }}.
              </p>
              <button
                @click="handleCloudCta"
                :disabled="connecting"
                class="px-4 py-2 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-white rounded-lg text-sm font-medium transition-all disabled:opacity-60"
              >
                {{ finishCheckoutNeeded ? 'Finish checkout' : (connecting ? 'Connecting…' : 'Connect Stimma Cloud') }}
              </button>
              <p v-if="connectError" class="text-xs text-red-500 mt-2">{{ connectError }}</p>
            </div>

            <!-- Bring your own AI path -->
            <div class="rounded-lg border border-edge bg-surface-raised p-4">
              <h4 class="text-sm font-semibold text-content mb-1.5">Bring your own AI</h4>
              <p class="text-sm text-content-tertiary leading-relaxed mb-3">
                {{ byoaiIntroText }}
              </p>
              <div class="flex flex-col gap-1.5 text-sm">
                <button
                  v-if="missingAgentLlm"
                  @click="openSettingsSection('ai-services')"
                  class="text-left text-content-secondary hover:text-content transition-colors"
                >
                  Configure a local LLM in <span class="font-medium">Settings → Advanced</span> →
                </button>
                <button
                  v-if="missingGeneration"
                  @click="openSettingsSection('tools')"
                  class="text-left text-content-secondary hover:text-content transition-colors"
                >
                  Connect ComfyUI or another tool provider in <span class="font-medium">Settings → Tools</span> →
                </button>
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
import { isTauri } from '../apiConfig'

const { readiness, shouldShowPanel, finishCheckoutNeeded, dontShowAgain, dismissPanel, setDontShowAgain } = useReadiness()
const { user, signInWithBrowser } = useAuth()
const { cloudBaseUrl, ensureCloudBaseUrl } = useCloudAccount()

const connecting = ref(false)
const connectError = ref('')

const missingAgentLlm = computed(() => !!readiness.value?.missing?.includes('agent_llm'))
const missingGeneration = computed(() => !!readiness.value?.missing?.includes('generation'))

const headline = computed(() => {
  if (finishCheckoutNeeded.value) return "Checkout didn't finish"
  if (missingAgentLlm.value && missingGeneration.value) return "Stimma needs an agent model and generation tools"
  if (missingAgentLlm.value) return "Stimma needs an agent model"
  return "Stimma needs generation tools"
})

const cloudCoversText = computed(() => {
  if (missingAgentLlm.value && missingGeneration.value) return 'a hosted agent model and generation tools'
  if (missingAgentLlm.value) return 'a hosted agent model'
  return 'hosted generation tools'
})

const byoaiIntroText = computed(() => {
  if (missingAgentLlm.value && missingGeneration.value) return 'Configure a local LLM and connect your own generation tools.'
  if (missingAgentLlm.value) return 'Configure a local LLM for the agent.'
  return 'Connect a generation tool of your own.'
})

function handleDismiss() {
  dismissPanel()
}

function handleDontShowToggle(e) {
  setDontShowAgain(e.target.checked)
}

function openSettingsSection(section) {
  dismissPanel()
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
    // Already signed in, just unsubscribed/lapsed — go straight to the plan
    // chooser on the web. No prices in-app; the web owns commerce.
    await ensureCloudBaseUrl()
    await openUrl(cloudBaseUrl.value + '/link/getstarted')
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
