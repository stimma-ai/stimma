<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="visible"
        class="fixed inset-0 z-[2000] flex items-center justify-center bg-black/75 px-5"
        @click.self="close"
      >
        <div class="w-full max-w-md rounded-lg border border-edge bg-surface p-6 text-center shadow-2xl">
          <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/15 text-red-500">
            <TrashIcon class="h-7 w-7" />
          </div>

          <h2 class="mb-3 text-xl font-semibold text-content">{{ title }}</h2>
          <p class="mb-4 text-sm leading-6 text-content-tertiary">{{ message }}</p>

          <p v-if="count > 0" class="mb-5 text-sm font-medium text-content">
            {{ countMessage || `This will move ${count} ${count === 1 ? 'item' : 'items'} to trash.` }}
          </p>

          <div class="flex justify-end gap-2">
            <button
              class="rounded-lg bg-surface-raised px-4 py-2 text-sm font-medium text-content transition-colors hover:bg-surface-hover"
              @click="close"
            >
              Cancel
            </button>
            <button
              class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700"
              @click="confirm"
            >
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { TrashIcon } from '@heroicons/vue/24/outline'

defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: 'Delete Item?'
  },
  message: {
    type: String,
    default: 'Are you sure you want to delete this item? It will be moved to trash and can be restored later.'
  },
  confirmText: {
    type: String,
    default: 'Delete'
  },
  count: {
    type: Number,
    default: 0
  },
  countMessage: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'confirm'])

function close() {
  emit('close')
}

function confirm() {
  emit('confirm')
  close()
}
</script>
