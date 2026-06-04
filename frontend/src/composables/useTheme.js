import { ref, computed, watchEffect, onUnmounted } from 'vue'
import { makeGlobalKey } from '../utils/storageKeys'

// Migrate legacy unscoped key
const _legacyThemeKey = 'stimma-theme'
const STORAGE_KEY = makeGlobalKey('theme')
if (localStorage.getItem(_legacyThemeKey) !== null) {
  localStorage.setItem(STORAGE_KEY, localStorage.getItem(_legacyThemeKey))
  localStorage.removeItem(_legacyThemeKey)
}

// Shared reactive state (singleton across all usages)
const themePreference = ref(localStorage.getItem(STORAGE_KEY) || 'system')

// Track system preference
const systemPrefersDark = ref(
  typeof window !== 'undefined'
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : true
)

// Listen for OS theme changes
let mediaQuery = null
let mediaListener = null

if (typeof window !== 'undefined') {
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  mediaListener = (e) => {
    systemPrefersDark.value = e.matches
  }
  mediaQuery.addEventListener('change', mediaListener)
}

const resolvedTheme = computed(() => {
  if (themePreference.value === 'system') {
    return systemPrefersDark.value ? 'dark' : 'light'
  }
  return themePreference.value
})

// Apply theme to DOM whenever resolved theme changes
watchEffect(() => {
  document.documentElement.setAttribute('data-theme', resolvedTheme.value)
})

function setTheme(preference) {
  themePreference.value = preference
  localStorage.setItem(STORAGE_KEY, preference)
}

export function useTheme() {
  return {
    themePreference,
    resolvedTheme,
    setTheme,
  }
}
