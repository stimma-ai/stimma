<template>
  <div class="w-48 bg-surface border border-edge-subtle rounded-lg shadow-lg py-1 z-menu">
    <!-- Pin/Unpin (always available) -->
    <button
      @click="$emit('toggle-pin')"
      class="w-full px-3 py-2 text-left text-xs text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors flex items-center gap-2"
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" :fill="pinned ? 'currentColor' : 'none'" :stroke="pinned ? 'none' : 'currentColor'" stroke-width="1.75">
        <path d="M16 3a1 1 0 0 1 .707.293l4 4a1 1 0 0 1-.464 1.664l-2.12.53-3.536 3.536.879 3.51a1 1 0 0 1-1.664.95L10 14.682l-5.293 5.293a1 1 0 0 1-1.414-1.414L8.586 13.268l-2.8-2.8a1 1 0 0 1 .95-1.664l3.51.879 3.536-3.536.53-2.121A1 1 0 0 1 16 3z" />
      </svg>
      {{ pinned ? 'Unpin from Sidebar' : 'Pin to Sidebar' }}
    </button>

    <!-- Reset to Defaults (optional) -->
    <template v-if="showResetDefaults">
      <div class="border-t border-edge-subtle my-1"></div>
      <button
        @click="$emit('reset-defaults')"
        class="w-full px-3 py-2 text-left text-xs text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors flex items-center gap-2"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
        </svg>
        Reset to Defaults
      </button>
    </template>

  </div>
</template>

<script setup lang="ts">
interface Props {
  pinned: boolean
  showResetDefaults?: boolean
}

withDefaults(defineProps<Props>(), {
  showResetDefaults: false
})

defineEmits<{
  (e: 'toggle-pin'): void
  (e: 'reset-defaults'): void
}>()
</script>
