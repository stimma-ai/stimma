<template>
  <div class="flex gap-1 mt-2 justify-end">
    <!-- Edit (user messages only) -->
    <button
      v-if="showReplay"
      @click.stop="$emit('edit')"
      class="p-0.5 rounded text-content-muted hover:text-blue-500 hover:bg-blue-900/30 transition-colors"
      title="Edit message"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
      </svg>
    </button>
    <!-- Replay (user messages only) -->
    <button
      v-if="showReplay"
      @click.stop="$emit('replay')"
      class="p-0.5 rounded text-content-muted hover:text-emerald-500 hover:bg-emerald-900/30 transition-colors"
      title="Clear chat and resend"
    >
      <!-- Custom replay icon: play with circular arrow -->
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
        <!-- Broken circle arc (from ~7 o'clock to ~2 o'clock) -->
        <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12a7.5 7.5 0 0 1 12.803-5.303" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12a7.5 7.5 0 0 1-12.803 5.303" />
        <!-- Arrow at 2 o'clock position -->
        <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 4.5l.803 2.197L19.5 7.5" />
        <!-- Play triangle (smaller, centered) -->
        <path stroke-linecap="round" stroke-linejoin="round" d="M10 8.5v7l5.5-3.5-5.5-3.5z" />
      </svg>
    </button>
    <!-- Trash (shift-click for trash-to-end) -->
    <button
      @click.stop="handleTrash($event)"
      class="p-0.5 rounded text-content-muted hover:text-red-500 hover:bg-red-500/10 transition-colors"
      title="Delete"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
      </svg>
    </button>
    <!-- Debug (open raw view focused on this item) - dev mode only -->
    <button
      v-if="devModeRef"
      @click.stop="$emit('debug')"
      class="p-0.5 rounded text-content-muted hover:text-purple-500 hover:bg-purple-500/10 transition-colors"
      title="Debug view"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0 1 12 12.75Zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 0 1-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 0 0 2.248-2.354M12 12.75a2.25 2.25 0 0 1-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 0 0-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 0 1 .4-2.253M12 8.25a2.25 2.25 0 0 0-2.248 2.146M12 8.25a2.25 2.25 0 0 1 2.248 2.146M8.683 5a6.032 6.032 0 0 1-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0 1 15.318 5m0 0c.427-.283.815-.62 1.155-.999a4.471 4.471 0 0 0-.575-1.752M4.921 6a24.048 24.048 0 0 0-.392 3.314c1.668.546 3.416.914 5.223 1.082M19.08 6c.205 1.08.337 2.187.392 3.314a23.882 23.882 0 0 1-5.223 1.082" />
      </svg>
    </button>
  </div>
</template>

<script setup>
import { devModeRef } from '../../appConfig'

defineProps({
  showReplay: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['edit', 'replay', 'delete', 'delete-from-here', 'debug'])

function handleTrash(event) {
  if (event.shiftKey) {
    emit('delete-from-here')
  } else {
    emit('delete')
  }
}
</script>
