<template>
  <button
    type="button"
    class="text-[12.5px] text-content-tertiary transition-colors hover:text-content-secondary"
    @click="openRedeem"
  >
    Have a code? <span class="font-medium text-content-secondary">Redeem it</span>
  </button>
</template>

<script setup>
// Code redemption is web-only: this quiet link opens the dashboard's redeem
// deep-link ({cloud}/link/redeem lands with the code field open + focused).
// The app reacts to the resulting balance_added push, so redeeming in the
// browser still lights up the app.
import { isTauri } from '../apiConfig'
import { useCloudAccount } from '../composables/useCloudAccount'

const { cloudBaseUrl, ensureCloudBaseUrl } = useCloudAccount()

async function openRedeem() {
  await ensureCloudBaseUrl()
  const url = `${cloudBaseUrl.value}/link/redeem`
  if (isTauri()) {
    try {
      const { open } = await import('@tauri-apps/plugin-shell')
      await open(url)
      return
    } catch {
      // fall through to window.open
    }
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}
</script>
