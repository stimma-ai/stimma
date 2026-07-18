<template>
  <div
    class="fixed inset-0 flex items-center justify-center overflow-hidden bg-base font-brand"
  >
    <!-- Theme picker — upper right -->
    <div class="absolute top-4 right-4 flex items-center gap-0.5 p-1 bg-surface-raised rounded-lg border border-edge">
      <Tooltip text="Light">
        <button
          @click="selectTheme('light')"
          class="flex items-center justify-center w-7 h-7 rounded-md transition-colors duration-150 border focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="currentTheme === 'light'
            ? 'bg-accent/15 border-accent/50 text-accent'
            : 'bg-transparent border-transparent text-content-muted hover:text-content'"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
          </svg>
        </button>
      </Tooltip>
      <Tooltip text="Dark">
        <button
          @click="selectTheme('dark')"
          class="flex items-center justify-center w-7 h-7 rounded-md transition-colors duration-150 border focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="currentTheme === 'dark'
            ? 'bg-accent/15 border-accent/50 text-accent'
            : 'bg-transparent border-transparent text-content-muted hover:text-content'"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
          </svg>
        </button>
      </Tooltip>
      <Tooltip text="System">
        <button
          @click="selectTheme('system')"
          class="flex items-center justify-center w-7 h-7 rounded-md transition-colors duration-150 border focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="currentTheme === 'system'
            ? 'bg-accent/15 border-accent/50 text-accent'
            : 'bg-transparent border-transparent text-content-muted hover:text-content'"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25A2.25 2.25 0 015.25 3h13.5A2.25 2.25 0 0121 5.25z" />
          </svg>
        </button>
      </Tooltip>
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
        @click="handleGetStarted"
        :disabled="loading"
        class="w-full max-w-[320px] px-[18px] py-[13px] rounded-md bg-accent text-white flex items-center justify-center gap-2 transition-all hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
        style="box-shadow: 0 2px 14px rgb(var(--color-accent-rgb) / 0.22);"
      >
        <span class="text-sm font-semibold whitespace-nowrap">Get started</span>
        <span class="text-[15px] opacity-85 flex-shrink-0">→</span>
      </button>

      <!-- Returning users -->
      <p class="mt-4 text-content-tertiary" style="font-size: 12.5px;">
        Have a Stimma account?
        <a
          href="#"
          @click.prevent="handleSignIn"
          class="text-content-secondary font-medium no-underline hover:text-content transition-colors"
        >Sign in</a>
      </p>

      <!-- Codes are redeemed on the website; the app reacts to the balance push -->
      <RedeemCodeLink class="mt-3" />

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
        <label class="relative inline-flex items-center cursor-pointer flex-shrink-0 w-8 h-[18px]">
          <input type="checkbox" v-model="shareAnalytics" class="peer sr-only">
          <div class="absolute inset-0 rounded-full bg-overlay-subtle peer-checked:bg-accent transition-colors duration-150"></div>
          <div class="absolute left-0.5 top-0.5 w-3.5 h-3.5 rounded-full bg-white shadow transition-transform duration-150 peer-checked:translate-x-3.5"></div>
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
import { useReadiness } from '../composables/useReadiness'
import RedeemCodeLink from '../components/RedeemCodeLink.vue'
import Tooltip from '../components/ui/Tooltip.vue'

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

const loading = ref(false)
const isOfficial = isOfficialBuild()

// Consent toggle default per compliance regime (official builds only):
// optin regimes (EEA/UK/CH) default OFF, optout regimes default ON.
// The region check is resolved before this view renders (cached in config
// after the first successful check; unreachable -> optin, re-checked next
// launch).
const shareAnalytics = ref(false)

const { checkStartupReadiness } = useReadiness()

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
  // App.vue's startup path skips the readiness check when it redirects here,
  // so run it now — the setup wizard shows itself right after onboarding if
  // this install's seen version is behind SETUP_WIZARD_VERSION.
  void checkStartupReadiness()
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

function handleGetStarted() {
  markComplete()
  router.push({ name: 'home' })
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
}</script>
