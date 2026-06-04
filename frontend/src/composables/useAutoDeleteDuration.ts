/**
 * Chat auto-delete is intentionally disabled.
 *
 * This composable always returns "never" for chat flows.
 * ToolView uses useToolAutoDeleteDuration instead.
 */
import { ref, readonly } from 'vue'

const autoDeleteDuration = ref<string>('never')

function setAutoDeleteDuration(_duration: string): void {
  autoDeleteDuration.value = 'never'
}

function loadDuration(): void {
  autoDeleteDuration.value = 'never'
}

/**
 * Composable for auto-delete duration management.
 * Returns a shared reactive reference to the duration setting.
 */
export function useAutoDeleteDuration() {
  return {
    autoDeleteDuration,
    autoDeleteDurationReadonly: readonly(autoDeleteDuration),
    setAutoDeleteDuration,
    reload: loadDuration
  }
}

// Also export the setter directly for convenience
export { setAutoDeleteDuration }
