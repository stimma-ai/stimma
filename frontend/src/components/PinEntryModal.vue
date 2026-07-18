<template>
  <Modal :show="show" size="custom" custom-class="w-80" :close-on-backdrop="false" @close="cancel">
    <template #header>
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-full bg-accent/20 flex items-center justify-center">
          <svg class="w-5 h-5 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
        </div>
        <div>
          <h3 class="text-lg font-semibold text-content">Profile Locked</h3>
          <p class="text-sm text-content-tertiary">{{ profileName || 'This profile' }}</p>
        </div>
      </div>
    </template>

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
        class="w-full px-4 py-3 bg-overlay-subtle border border-transparent rounded-lg text-content text-center text-xl tracking-widest focus:outline-none focus:border-accent focus-visible:ring-2 ring-accent/40"
        placeholder="PIN"
        autocomplete="off"
        @keydown.enter="submit"
      />

      <!-- Error message -->
      <p v-if="error" class="mt-2 text-sm text-red-500 text-center">
        {{ error }}
      </p>
    </div>

    <template #footer>
      <Button v-if="showCancel" variant="secondary" class="flex-1" @click="cancel">
        Cancel
      </Button>
      <Button variant="primary" class="flex-1" :disabled="!pinValue" :loading="isSubmitting" @click="submit">
        {{ isSubmitting ? 'Verifying...' : 'Unlock' }}
      </Button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import Modal from './ui/Modal.vue'
import Button from './ui/Button.vue'

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
