<script setup lang="ts">
// Atelier ConfirmDialog — absorbs ConfirmModal + DeleteConfirmModal
// (STANDARDS.md §2). Built on Modal.vue + Button.vue so every confirm in
// the app shares one backdrop/z-index/transition/button implementation.
import Modal from './Modal.vue'
import Button from './Button.vue'

const props = withDefaults(defineProps<{
  show: boolean
  title?: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Confirm button renders as Button danger variant instead of primary. */
  danger?: boolean
  /** Loading state on the confirm button; also suppresses Esc/backdrop close. */
  busy?: boolean
  closeOnBackdrop?: boolean
  nested?: boolean
}>(), {
  title: 'Confirm',
  message: '',
  confirmLabel: 'Confirm',
  cancelLabel: 'Cancel',
  danger: false,
  busy: false,
  closeOnBackdrop: true,
  nested: false,
})

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

function cancel() {
  if (props.busy) return
  emit('cancel')
}

function confirm() {
  emit('confirm')
}
</script>

<template>
  <Modal
    :show="show"
    size="sm"
    :close-on-backdrop="closeOnBackdrop && !busy"
    :close-on-esc="!busy"
    :nested="nested"
    @close="cancel"
  >
    <div class="px-6 py-5 text-center">
      <div v-if="$slots.icon" class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full">
        <slot name="icon" />
      </div>

      <h3 class="mb-2 text-lg font-semibold text-content">{{ title }}</h3>

      <div class="text-sm text-content-secondary whitespace-pre-line">
        <slot>{{ message }}</slot>
      </div>
    </div>

    <template #footer>
      <Button variant="secondary" :disabled="busy" @click="cancel">
        {{ cancelLabel }}
      </Button>
      <Button :variant="danger ? 'danger' : 'primary'" :loading="busy" @click="confirm">
        {{ confirmLabel }}
      </Button>
    </template>
  </Modal>
</template>
