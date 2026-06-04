/**
 * Toast notification system.
 *
 * Provides reactive toast notifications that can be triggered from anywhere
 * in the app, including WebSocket handlers.
 *
 * Singleton pattern - all components share the same toast queue.
 */
import { ref, readonly } from 'vue'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface Toast {
  id: number
  message: string
  type: ToastType
  duration: number
  action?: ToastAction
}

// Global reactive state (shared across all components using this composable)
const toasts = ref<Toast[]>([])
let nextId = 1

/**
 * Add a toast notification
 * @param message - The message to display
 * @param type - Toast type (success, error, warning, info)
 * @param duration - Duration in ms before auto-dismiss (0 = no auto-dismiss)
 * @returns The toast id
 */
function addToast(message: string, type: ToastType = 'info', duration: number = 4000, action?: ToastAction): number {
  const id = nextId++
  const toast: Toast = { id, message, type, duration, action }

  toasts.value.push(toast)

  // Auto-remove after duration (if duration > 0)
  if (duration > 0) {
    setTimeout(() => {
      removeToast(id)
    }, duration)
  }

  return id
}

/**
 * Remove a toast by id
 */
function removeToast(id: number): void {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
}

/**
 * Clear all toasts
 */
function clearToasts(): void {
  toasts.value = []
}

/**
 * Composable for toast notifications.
 * Returns a shared reactive reference to the toasts array and methods.
 */
export function useToasts() {
  return {
    // Reactive state (readonly to prevent external mutation)
    toasts: readonly(toasts),

    // Methods
    addToast,
    removeToast,
    clearToasts
  }
}

// Export methods directly for use outside of Vue components (e.g., WebSocket handlers)
export { addToast, removeToast, clearToasts }
