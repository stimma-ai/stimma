import { ref, watch } from 'vue'

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
let isNavigatingHistory = false

export function useTabNavigation() {
  // Switch to a different tab
  function switchToTab(tabName) {
    if (activeTab.value === tabName) return
    activeTab.value = tabName
    slideshowActive.value = false // Reset when switching tabs

    // Push to browser history (unless we're handling a popstate)
    if (!isNavigatingHistory) {
      window.history.pushState(
        { tab: tabName, slideshow: false },
        '',
        `#${tabName}`
      )
    }
  }

  // Notify that slideshow mode entered (called by sections)
  function enterSlideshowMode() {
    slideshowActive.value = true

    // Use replaceState instead of pushState to avoid adding extra history entries
    // that interfere with Vue Router navigation
    if (!isNavigatingHistory) {
      window.history.replaceState(
        { tab: activeTab.value, slideshow: true },
        '',
        `#${activeTab.value}/slideshow`
      )
    }
  }

  // Notify that slideshow mode exited (called by sections)
  function exitSlideshowMode() {
    slideshowActive.value = false

    // Update the URL to remove /slideshow without navigating back in history
    // Using replaceState instead of back() to avoid interfering with Vue Router
    if (!isNavigatingHistory) {
      window.history.replaceState(
        { tab: activeTab.value, slideshow: false },
        '',
        `#${activeTab.value}`
      )
    }
  }

  // Initialize browser history integration
  function initHistoryIntegration() {
    // Set initial state
    window.history.replaceState(
      { tab: activeTab.value, slideshow: false },
      '',
      `#${activeTab.value}`
    )

    // Handle browser back/forward
    window.addEventListener('popstate', (event) => {
      isNavigatingHistory = true

      if (event.state?.tab) {
        activeTab.value = event.state.tab
        slideshowActive.value = event.state.slideshow || false
      }

      setTimeout(() => {
        isNavigatingHistory = false
      }, 0)
    })
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
