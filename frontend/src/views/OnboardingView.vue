<template>
  <div
    class="fixed inset-0 flex items-center justify-center overflow-hidden bg-base"
    style="font-family: 'General Sans', system-ui, sans-serif;"
  >
    <!-- Theme picker — upper right -->
    <div class="absolute top-4 right-4 flex items-center gap-0.5 p-1 bg-surface-raised rounded-lg border border-edge">
      <button
        @click="selectTheme('light')"
        class="flex items-center justify-center w-7 h-7 rounded transition-all border"
        :class="currentTheme === 'light'
          ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
          : 'bg-transparent border-transparent text-content-muted hover:text-content'"
        title="Light"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
        </svg>
      </button>
      <button
        @click="selectTheme('dark')"
        class="flex items-center justify-center w-7 h-7 rounded transition-all border"
        :class="currentTheme === 'dark'
          ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
          : 'bg-transparent border-transparent text-content-muted hover:text-content'"
        title="Dark"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
        </svg>
      </button>
      <button
        @click="selectTheme('system')"
        class="flex items-center justify-center w-7 h-7 rounded transition-all border"
        :class="currentTheme === 'system'
          ? 'bg-blue-500/15 border-blue-500/50 text-blue-500'
          : 'bg-transparent border-transparent text-content-muted hover:text-content'"
        title="System"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25A2.25 2.25 0 015.25 3h13.5A2.25 2.25 0 0121 5.25z" />
        </svg>
      </button>
    </div>

    <!-- Main content -->
    <div class="w-full max-w-[380px] px-7 flex flex-col items-center">

      <!-- Brand -->
      <div class="flex flex-col items-center gap-3.5 mb-[52px]">
        <img src="/logo.png" alt="Stimma" class="w-14 h-14">
        <span class="text-content" style="font-size: 1.7rem; font-weight: 500; letter-spacing: 0.12em; line-height: 1;">stimma</span>
        <span class="text-[13px] text-content-tertiary">Your workshop for images, video, and design.</span>
      </div>

      <!-- Primary CTA -->
      <button
        @click="handleCreateAccount"
        :disabled="loading"
        class="w-full max-w-[320px] px-[18px] py-[14px] rounded-xl text-white flex items-center justify-between gap-3 transition-all hover:brightness-105 hover:-translate-y-px active:translate-y-0 active:brightness-95 disabled:opacity-60"
        style="background: linear-gradient(135deg, #0d9488, #06b6d4, #6366f1); box-shadow: 0 2px 14px rgba(13,148,136,0.18);"
      >
        <div class="flex-1 text-center">
          <span class="text-sm font-semibold whitespace-nowrap">Create your Stimma account</span>
        </div>
        <span class="text-[17px] opacity-85 flex-shrink-0">→</span>
      </button>

      <!-- Already have account -->
      <p class="mt-3 text-content-secondary" style="font-size: 12.5px;">
        Already have an account?
        <a
          href="#"
          @click.prevent="handleSignIn"
          class="text-content font-medium no-underline hover:text-content transition-colors"
        >Sign in</a>
      </p>

    </div>

    <!-- Skip / confirm — fixed between content and compliance -->
    <div class="fixed flex flex-col items-center" style="bottom: 110px; left: 0; right: 0;">
      <!-- Skip button -->
      <template v-if="!showConfirm">
        <button
          @click="showConfirm = true"
          class="bg-transparent border-none text-content-secondary hover:text-content cursor-pointer p-0 transition-colors"
          style="font-family: 'General Sans', system-ui, sans-serif; font-size: 12.5px; font-weight: 500; text-decoration: underline; text-underline-offset: 2px;"
        >Continue without an account</button>
        <span class="text-content-muted mt-1.5" style="font-size: 11px;">Requires local LLM and generation tools</span>
      </template>

      <!-- Confirm card — appears in the same spot -->
      <div
        v-else
        class="w-full max-w-[380px] px-7"
      >
        <div class="rounded-xl p-[18px] bg-surface border border-edge">
          <p class="mb-3.5 text-content-secondary" style="font-size: 13px; line-height: 1.6;">
            You'll connect Stimma to <strong class="text-content font-medium">your own local AI models</strong>. You can always create an account later.
          </p>
          <div class="flex gap-2">
            <button
              @click="showConfirm = false"
              class="flex-1 py-2.5 rounded-lg cursor-pointer bg-transparent border border-edge text-content-secondary hover:bg-overlay-subtle transition-colors"
              style="font-family: 'General Sans', system-ui, sans-serif; font-size: 12.5px; font-weight: 500;"
            >← Back</button>
            <button
              @click="handleContinueWithoutAccount"
              class="rounded-lg cursor-pointer bg-overlay-subtle border border-edge text-content hover:bg-overlay-hover transition-colors"
              style="flex: 2; padding: 10px 0; font-family: 'General Sans', system-ui, sans-serif; font-size: 12.5px; font-weight: 500;"
            >Continue without account</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Compliance footer — pinned to bottom, no box -->
    <div class="fixed bottom-0 left-0 right-0 px-7 pb-[22px] flex flex-col items-center" style="gap: 10px; background: var(--color-base); border-top: 1px solid var(--color-border-subtle); padding-top: 14px;">

      <!-- Telemetry — inline, no card. Official builds: consent toggle
           (default per compliance regime). Source builds: telemetry is
           permanently disabled, so there is no consent control. -->
      <div v-if="isOfficial" class="flex items-center" style="gap: 10px;">
        <span class="text-content-secondary" style="font-size: 11px;">
          Share usage telemetry to help improve Stimma.
          <a @click.prevent="openUrl(learnMoreUrl)" href="#" class="text-content-secondary underline underline-offset-2 hover:text-content transition-colors">Learn&nbsp;more.</a>
        </span>
        <label class="relative cursor-pointer flex-shrink-0" style="width: 32px; height: 18px;">
          <input type="checkbox" v-model="shareAnalytics" class="opacity-0 absolute w-0 h-0">
          <div
            class="absolute inset-0 rounded-full transition-all duration-200"
            :style="shareAnalytics ? 'background: linear-gradient(90deg, #0d9488, #06b6d4)' : 'background: var(--color-overlay-light)'"
          ></div>
          <div
            class="absolute rounded-full bg-white transition-transform duration-200"
            style="top: 2px; width: 14px; height: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.2);"
            :style="shareAnalytics ? 'transform: translateX(14px)' : 'transform: translateX(2px)'"
          ></div>
        </label>
      </div>

      <!-- Legal -->
      <p class="text-content-secondary text-center" style="font-size: 10.5px; line-height: 1.5;">
        By continuing you agree to our
        <a @click.prevent="openUrl(termsUrl)" href="#" class="text-content-secondary underline underline-offset-2 hover:text-content transition-colors">Terms of Service</a>
        and
        <a @click.prevent="openUrl(privacyUrl)" href="#" class="text-content-secondary underline underline-offset-2 hover:text-content transition-colors">Privacy Policy</a>.
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { signInWithBrowser } from '../composables/useAuth'
import { isOfficialBuild } from '../distribution'
import { makeGlobalKey } from '../utils/storageKeys'
import { getApiBase } from '../apiConfig'
import { useCloudAccount } from '../composables/useCloudAccount'
import { useTheme } from '../composables/useTheme'
import { useSettingsApi } from '../composables/useSettingsApi'
import { useTelemetry } from '../composables/useTelemetry'

const router = useRouter()
const { track } = useTelemetry()
const { cloudBaseUrl } = useCloudAccount()
const { themePreference: currentTheme, setTheme } = useTheme()
const { updateTheme } = useSettingsApi()

const termsUrl = computed(() => `${cloudBaseUrl.value}/link/terms`)
const privacyUrl = computed(() => `${cloudBaseUrl.value}/link/privacy`)
const learnMoreUrl = computed(() => `${cloudBaseUrl.value}/link/telemetry`)

async function openUrl(url) {
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank')
  }
}

function selectTheme(theme) {
  setTheme(theme)
  updateTheme(theme).catch(() => {})
}

const showConfirm = ref(false)
const loading = ref(false)
const isOfficial = isOfficialBuild()

// Consent toggle default per compliance regime (official builds only):
// optin regimes (EEA/UK/CH) default OFF, optout regimes default ON.
// The region check is resolved before this view renders (cached in config
// after the first successful check; unreachable -> optin, re-checked next
// launch).
const shareAnalytics = ref(false)

if (isOfficial) {
  fetch(`${getApiBase()}/compliance/region`)
    .then((r) => (r.ok ? r.json() : null))
    .then((region) => {
      shareAnalytics.value = region?.regime === 'optout'
    })
    .catch(() => {
      shareAnalytics.value = false // optin-safe default
    })
}

function markComplete() {
  localStorage.setItem(makeGlobalKey('onboarding_completed'), '1')
  // Activation-funnel endpoint. Tracked BEFORE the consent decision lands so
  // it buffers pre-consent and flushes together with first_run on consent-on.
  track('onboarding_completed', {}, 'app')
  // Record the consent decision (official builds only). Until this lands,
  // consent is undetermined and the backend buffers events locally with
  // zero network (D14); dev builds have telemetry permanently disabled.
  if (isOfficial) {
    saveAnalyticsPref(shareAnalytics.value)
  }
}

async function saveAnalyticsPref(enabled) {
  try {
    await fetch(`${getApiBase()}/settings/telemetry`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
  } catch {
    // Non-fatal — adjustable in Settings later
  }
}

async function handleCreateAccount() {
  loading.value = true
  try {
    await signInWithBrowser('create')
    markComplete()
    router.push({ name: 'home' })
  } catch {
    loading.value = false
  }
}

async function handleSignIn() {
  loading.value = true
  try {
    await signInWithBrowser('sign-in')
    markComplete()
    router.push({ name: 'home' })
  } catch {
    loading.value = false
  }
}

function handleContinueWithoutAccount() {
  markComplete()
  router.push({ name: 'home' })
}
</script>
