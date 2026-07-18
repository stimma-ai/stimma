<template>
  <ConfirmDialog
    :show="visible"
    :title="title"
    :confirm-label="confirmText"
    danger
    @confirm="confirm"
    @cancel="close"
  >
    <template #icon>
      <div class="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/15 text-red-500">
        <TrashIcon class="h-7 w-7" />
      </div>
    </template>

    <p class="text-sm leading-6 text-content-tertiary">{{ message }}</p>
    <p v-if="count > 0" class="mt-3 text-sm font-medium text-content">
      {{ countMessage || `This will move ${count} ${count === 1 ? 'item' : 'items'} to trash.` }}
    </p>
  </ConfirmDialog>
</template>

<script setup>
// Thin wrapper kept for call-site compatibility (BrowseGridView) — renders
// via ui/ConfirmDialog.vue. Props/emits unchanged.
import { TrashIcon } from '@heroicons/vue/24/outline'
import ConfirmDialog from './ui/ConfirmDialog.vue'

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
