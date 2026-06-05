import { onMounted, onUnmounted, onActivated, onDeactivated, ref } from 'vue'

/**
 * Global keyboard shortcuts handler
 * Handles ESC and other global shortcuts contextually based on what's visible.
 * Properly handles Vue KeepAlive by pausing handlers when component is deactivated.
 */
export function useGlobalKeyboardShortcuts(options = {}) {
  const {
    onEscapePressed,
    onKeydown,  // General keydown handler (receives event)
    isActive = () => true  // Function to determine if this handler should be active
  } = options

  // Track whether the component is currently active (not deactivated by KeepAlive)
  const isComponentActive = ref(true)

  function handleGlobalKeydown(event) {
    // Don't handle if component is deactivated (KeepAlive)
    if (!isComponentActive.value) {
      return
    }

    // Don't handle if user is typing in an input/textarea
    const activeElement = document.activeElement
    if (activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA')) {
      return
    }

    // Don't handle if this handler is not active
    if (!isActive()) {
      return
    }

    // If general keydown handler is provided, use it
    if (onKeydown) {
      onKeydown(event)
      return
    }

    // Otherwise, handle specific keys
    if (event.key === 'Escape') {
      if (onEscapePressed) {
        event.preventDefault()
        onEscapePressed()
      }
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleGlobalKeydown)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleGlobalKeydown)
  })

  // Handle KeepAlive activation/deactivation
  onActivated(() => {
    isComponentActive.value = true
  })

  onDeactivated(() => {
    isComponentActive.value = false
  })

  return {
    handleGlobalKeydown,
    isComponentActive
  }
}
