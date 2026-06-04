<template>
  <div class="fixed bottom-4 right-4 z-[10100] flex flex-col gap-2 pointer-events-none">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="pointer-events-auto max-w-sm px-4 py-3 rounded-lg shadow-lg border border-edge bg-surface text-content flex items-start gap-3 backdrop-blur-sm"
      >
        <!-- Icon (only colored element) -->
        <div class="flex-shrink-0 mt-0.5" :class="iconColor(toast.type)">
          <component :is="getIcon(toast.type)" class="w-5 h-5" />
        </div>

        <!-- Message + Action -->
        <div class="flex-1 flex items-center gap-3">
          <p class="text-sm">{{ toast.message }}</p>
          <button
            v-if="toast.action"
            @click="handleAction(toast)"
            class="text-sm font-medium underline underline-offset-2 hover:opacity-80 transition-opacity whitespace-nowrap"
          >
            {{ toast.action.label }}
          </button>
        </div>

        <!-- Close button -->
        <button
          @click="removeToast(toast.id)"
          class="flex-shrink-0 p-0.5 rounded hover:bg-overlay-light transition-colors"
        >
          <svg class="w-4 h-4 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { h } from 'vue'
import { useToasts, type ToastType } from '../composables/useToasts'

const { toasts, removeToast } = useToasts()

function handleAction(toast: any) {
  if (toast.action?.onClick) {
    toast.action.onClick()
  }
  removeToast(toast.id)
}

function iconColor(type: ToastType): string {
  switch (type) {
    case 'success':
      return 'text-green-600 dark:text-green-500'
    case 'error':
      return 'text-red-600 dark:text-red-500'
    case 'warning':
      return 'text-amber-600 dark:text-yellow-400'
    case 'info':
    default:
      return 'text-blue-600 dark:text-blue-400'
  }
}

// Icon components for each type
function getIcon(type: ToastType) {
  const iconPaths: Record<ToastType, string> = {
    success: 'M5 13l4 4L19 7',
    error: 'M6 18L18 6M6 6l12 12',
    warning: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
    info: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  }

  return {
    render() {
      return h('svg', {
        class: 'w-5 h-5',
        fill: 'none',
        viewBox: '0 0 24 24',
        stroke: 'currentColor',
        'stroke-width': '2'
      }, [
        h('path', {
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
          d: iconPaths[type]
        })
      ])
    }
  }
}
</script>

<style scoped>
/* Slide-in animation */
.toast-enter-active {
  transition: all 0.3s ease-out;
}

.toast-leave-active {
  transition: all 0.2s ease-in;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

.toast-move {
  transition: transform 0.3s ease;
}
</style>
