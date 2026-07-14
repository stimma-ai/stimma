import { ref } from 'vue'

// Tab names
export const TAB_NAMES = {
  BROWSE: 'browse',
  GENERATE: 'generate',
  BOARDS: 'boards',
  TRASH: 'trash'
}

// Singleton state
const activeTab = ref(TAB_NAMES.BROWSE)
const slideshowActive = ref(false) // Tracks if ANY section has slideshow active

export function useTabNavigation() {
  // Switch to a different tab
  function switchToTab(tabName) {
    if (activeTab.value === tabName) return
    activeTab.value = tabName
    slideshowActive.value = false // Reset when switching tabs
  }

  // Notify that slideshow mode entered (called by sections)
  function enterSlideshowMode() {
    slideshowActive.value = true
  }

  // Notify that slideshow mode exited (called by sections)
  function exitSlideshowMode() {
    slideshowActive.value = false
  }

  // Legacy no-op retained for callers outside this checkout. Vue Router owns
  // browser history; slideshow visibility must never rewrite the current route
  // or its history state, since that state identifies the active tool instance.
  function initHistoryIntegration() {
    return undefined
  }

  return {
    // State
    activeTab,
    slideshowActive,

    // Methods
    switchToTab,
    enterSlideshowMode,
    exitSlideshowMode,
    initHistoryIntegration,

    // Constants
    TAB_NAMES
  }
}
