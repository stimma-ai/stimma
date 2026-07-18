<template>
  <ConfirmDialog
    :show="show"
    :title="title"
    :message="message"
    :confirm-label="confirmText"
    :cancel-label="cancelText"
    danger
    @confirm="confirm"
    @cancel="cancel"
  />
</template>

<script setup>
// Thin wrapper kept for call-site compatibility (~9 usages across
// settings/views) — renders via ui/ConfirmDialog.vue. Props/emits are
// unchanged; do not rename without auditing every call site.
import ConfirmDialog from './ui/ConfirmDialog.vue'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: 'Confirm'
  },
  message: {
    type: String,
    required: true
  },
  confirmText: {
    type: String,
    default: 'Delete'
  },
  cancelText: {
    type: String,
    default: 'Cancel'
  }
})

const emit = defineEmits(['confirm', 'cancel'])

function confirm() {
  emit('confirm')
}

function cancel() {
  emit('cancel')
}
</script>
