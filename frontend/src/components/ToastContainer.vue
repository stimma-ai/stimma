<template>
  <!-- Above the chat dock's rows when there are any (desktop). -->
  <div class="fixed right-4 z-toast flex flex-col gap-2 pointer-events-none" :class="liftForDock ? 'bottom-16' : 'bottom-4'">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="pointer-events-auto max-w-sm px-4 py-3 rounded-lg shadow-lg border border-edge bg-surface text-content flex items-start gap-3 backdrop-blur-sm"
      >
        <!-- Icon (only colored element) -->
        <div class="flex-shrink-0 mt-0.5" :class="iconColor(toast.type)">
          <component :is="getIcon(toast.type)" class="w-icon-nav h-icon-nav" />
        </div>

        <!-- Message + Action, and any pictures it carries -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-3">
            <p class="text-sm min-w-0 truncate">{{ toast.message }}</p>
            <button
              v-if="toast.action"
              @click="handleAction(toast)"
              class="text-sm font-medium underline underline-offset-2 hover:opacity-80 transition-opacity whitespace-nowrap"
            >
              {{ toast.action.label }}
            </button>
          </div>
          <div v-if="toast.media?.mediaIds.length" class="mt-2 flex items-center gap-1.5">
            <button
              v-for="(mediaId, index) in toast.media.mediaIds.slice(0, MEDIA_MAX)"
              :key="mediaId"
              type="button"
              class="w-10 h-10 flex-none rounded-media overflow-hidden bg-matte hover:ring-2 hover:ring-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
              :aria-label="`View result ${index + 1}`"
              @click="toast.media.onMedia(mediaId, index)"
            >
              <MediaImage :media-id="mediaId" :thumbnail="true" :thumbnail-size="128" container-class="w-full h-full" img-class="w-full h-full object-cover" />
            </button>
            <span v-if="toast.media.mediaIds.length > MEDIA_MAX" class="px-1 text-xs font-mono tabular-nums text-content-muted">+{{ toast.media.mediaIds.length - MEDIA_MAX }}</span>
          </div>
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
import { computed, h } from 'vue'
import { useToasts, type ToastType } from '../composables/useToasts'
import { useChatDock } from '../composables/useChatDock'
import { useViewport } from '../composables/useViewport'
import { MediaImage } from './media'

const MEDIA_MAX = 6
const { entries: dockEntries } = useChatDock()
const { isCompact } = useViewport()
const liftForDock = computed(() => !isCompact.value && dockEntries.value.length > 0)
import { textClass, type StatusBucket } from '../utils/statusColors'

const { toasts, removeToast } = useToasts()

function handleAction(toast: any) {
  if (toast.action?.onClick) {
    toast.action.onClick()
  }
  removeToast(toast.id)
}

const TOAST_BUCKET: Record<ToastType, StatusBucket> = {
  success: 'done',
  error: 'failed',
  warning: 'warning',
  info: 'running',
}

function iconColor(type: ToastType): string {
  return textClass(TOAST_BUCKET[type] ?? 'running')
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
