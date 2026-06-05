<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="modal-overlay" @click.self="close">
        <div class="modal-content">
          <!-- Icon -->
          <div class="icon-container">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>

          <!-- Title & Message -->
          <h2>{{ title }}</h2>
          <p class="message">{{ message }}</p>

          <p v-if="count > 0" class="count-text">
            {{ countMessage || `This will move ${count} ${count === 1 ? 'item' : 'items'} to trash.` }}
          </p>

          <!-- Actions -->
          <div class="actions">
            <button class="cancel-button" @click="close">
              Cancel
            </button>
            <button class="confirm-button" @click="confirm">
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
const props = defineProps({
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

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 20px;
}

.modal-content {
  background-color: var(--color-surface);
  border-radius: 12px;
  max-width: 400px;
  width: 100%;
  padding: 24px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  text-align: center;
}

.icon-container {
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  background-color: #7f1d1d;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-container svg {
  width: 28px;
  height: 28px;
  color: #ef4444;
}

h2 {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0 0 12px 0;
}

.message {
  font-size: 0.875rem;
  color: var(--color-text-tertiary);
  margin: 0 0 16px 0;
  line-height: 1.5;
}

.count-text {
  font-size: 0.875rem;
  color: var(--color-text-primary);
  margin: 0 0 20px 0;
}

.count-text strong {
  color: #ef4444;
  font-weight: 600;
}

.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.cancel-button,
.confirm-button {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  border: none;
}

.cancel-button {
  background-color: var(--color-surface-raised);
  color: var(--color-text-secondary);
}

.cancel-button:hover {
  background-color: var(--color-surface-hover);
}

.confirm-button {
  background-color: #dc2626;
  color: white;
}

.confirm-button:hover {
  background-color: #b91c1c;
}

/* Animations */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform 0.3s ease;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.9);
}
</style>
