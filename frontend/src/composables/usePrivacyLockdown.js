import { readonly, ref } from 'vue'

const privacyLockdownActive = ref(false)

export function setPrivacyLockdownActive(active) {
  privacyLockdownActive.value = active === true
}

export function isPrivacyLockdownActive() {
  return privacyLockdownActive.value === true
}

export function usePrivacyLockdown() {
  return {
    privacyLockdownActive: readonly(privacyLockdownActive),
  }
}
