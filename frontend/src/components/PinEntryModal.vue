<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @keydown.esc="cancel"
      >
        <div
          class="bg-surface border border-edge rounded-lg shadow-2xl w-80 mx-4"
          @click.stop
        >
          <!-- Header with lock icon -->
          <div class="px-6 py-4 border-b border-edge flex items-center gap-3">
            <div class="w-10 h-10 rounded-full bg-blue-500/20 flex items-center justify-center">
              <svg class="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div>
              <h3 class="text-lg font-semibold text-content">Profile Locked</h3>
              <p class="text-sm text-content-tertiary">{{ profileName || 'This profile' }}</p>
            </div>
          </div>

          <!-- PIN Input -->
          <div class="px-6 py-4">
            <label class="block text-sm text-content-tertiary mb-2">Enter PIN to unlock</label>
            <input
              ref="pinInput"
              v-model="pinValue"
              type="password"
              inputmode="numeric"
              pattern="[0-9]*"
              maxlength="20"
              class="w-full px-4 py-3 bg-base border border-edge rounded-lg text-content text-center text-xl tracking-widest focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
              placeholder="PIN"
              autocomplete="off"
              @keydown.enter="submit"
            />

            <!-- Error message -->
            <p v-if="error" class="mt-2 text-sm text-red-500 text-center">
              {{ error }}
            </p>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 border-t border-edge flex gap-3">
            <button
              v-if="showCancel"
              @click="cancel"
              class="flex-1 px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              @click="submit"
              :disabled="!pinValue || isSubmitting"
              class="flex-1 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
            >
              <svg v-if="isSubmitting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>{{ isSubmitting ? 'Verifying...' : 'Unlock' }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  profileName: {
    type: String,
    default: ''
  },
  error: {
    type: String,
    default: ''
  },
  showCancel: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['submit', 'cancel'])

const pinInput = ref(null)
const pinValue = ref('')
const isSubmitting = ref(false)

// Focus input when modal opens
watch(() => props.show, (newVal) => {
  if (newVal) {
    pinValue.value = ''
    isSubmitting.value = false
    nextTick(() => {
      pinInput.value?.focus()
    })
  }
})

// Reset submitting state when error changes
watch(() => props.error, () => {
  isSubmitting.value = false
})

function submit() {
  if (!pinValue.value || isSubmitting.value) return
  isSubmitting.value = true
  emit('submit', pinValue.value)
}

function cancel() {
  emit('cancel')
}
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .bg-surface,
.modal-leave-active .bg-surface {
  transition: transform 0.15s ease;
}

.modal-enter-from .bg-surface,
.modal-leave-to .bg-surface {
  transform: scale(0.95);
}
</style>
