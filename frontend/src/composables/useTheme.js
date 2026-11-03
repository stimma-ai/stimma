import { ref, computed, watchEffect, onUnmounted } from 'vue'
import { makeGlobalKey, makeInstallKey } from '../utils/storageKeys'

// A person's theme belongs to the device they're looking at. Read before the
// bundle loads to prevent a flash (index.html, mobile/main.ts), so the key can't
// depend on which server this client is driving. Older installs kept it under a
// key that did; the first read carries that over.
const STORAGE_KEY = makeInstallKey('theme')
if (localStorage.getItem(STORAGE_KEY) === null) {
  const previous = localStorage.getItem(makeGlobalKey('theme'))
  if (previous !== null) localStorage.setItem(STORAGE_KEY, previous)
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
