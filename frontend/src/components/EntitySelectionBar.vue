<template>
  <Transition name="entity-bar-slide-up">
    <div v-if="visible" class="entity-selection-bar">
      <div class="entity-bar-content">
        <!-- Selection controls (left) -->
        <div class="flex items-center gap-3">
          <!-- Clear selection button (X) -->
          <button
            @click="$emit('clear')"
            class="flex items-center justify-center w-7 h-7 rounded hover:bg-overlay-medium transition-colors text-content-muted hover:text-content"
            title="Clear selection"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>

          <!-- Count text -->
          <span class="text-xs text-content-secondary whitespace-nowrap">
            {{ selectedCount }} of {{ totalCount }} selected
          </span>

          <!-- Select All -->
          <button
            v-if="selectedCount < totalCount"
            @click="$emit('select-all')"
            class="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap"
          >
            Select All
          </button>
        </div>

        <!-- Actions (right) -->
        <div class="flex items-center gap-2">
          <!-- Delete -->
          <button
            @click="$emit('delete')"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-red-400 hover:bg-red-500/15 transition-colors"
            title="Delete selected"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
            </svg>
            <span>Delete</span>
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
defineProps({
  visible: Boolean,
  selectedCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  entityType: { type: String, default: 'chat' }
})

defineEmits(['clear', 'select-all', 'delete'])
</script>

<style scoped>
.entity-selection-bar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 30; /* z-chrome: in-page floating chrome */
  background: var(--color-surface);
  border: 1px solid var(--color-edge-subtle);
  border-radius: 12px;
  max-width: 600px;
  width: max-content;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15), 0 4px 8px rgba(0, 0, 0, 0.1);
}

.entity-bar-content {
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

/* Slide up animation */
.entity-bar-slide-up-enter-active,
.entity-bar-slide-up-leave-active {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;
}

.entity-bar-slide-up-enter-from,
.entity-bar-slide-up-leave-to {
  transform: translate(-50%, 120%);
  opacity: 0;
}

.entity-bar-slide-up-enter-to,
.entity-bar-slide-up-leave-from {
  transform: translate(-50%, 0);
  opacity: 1;
}
</style>
