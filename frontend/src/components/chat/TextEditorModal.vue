<template>
  <Modal
    :show="true"
    size="custom"
    custom-class="max-w-[900px] w-full max-h-[85vh] flex flex-col"
    @close="close"
  >
    <template #header>
      <div class="flex justify-between items-center">
        <h2 class="m-0 text-lg font-semibold text-content">{{ title }}</h2>
        <IconButton @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

    <div class="flex-1 p-6 overflow-hidden flex flex-col">
      <textarea
        ref="textareaRef"
        v-model="localValue"
        :placeholder="placeholder"
        class="flex-1 w-full min-h-[450px] bg-surface text-content text-sm border border-edge rounded-lg px-4 py-3 focus:outline-none focus:border-accent resize-none"
      />
      <p v-if="hint" class="text-xs text-content-muted mt-3 leading-relaxed">
        {{ hint }}
      </p>
    </div>

    <template #footer>
      <Button variant="secondary" @click="close">
        Cancel
      </Button>
      <Button variant="primary" @click="save">
        Save
      </Button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import Modal from '../ui/Modal.vue'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'

const props = defineProps<{
  modelValue: string
  title?: string
  placeholder?: string
  hint?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'close'): void
  (e: 'save', value: string): void
}>()

const localValue = ref(props.modelValue)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

watch(() => props.modelValue, (newVal) => {
  localValue.value = newVal
})

function close() {
  emit('close')
}

function save() {
  emit('update:modelValue', localValue.value)
  emit('save', localValue.value)
  emit('close')
}

onMounted(() => {
  // Focus and move cursor to end
  if (textareaRef.value) {
    textareaRef.value.focus()
    textareaRef.value.selectionStart = textareaRef.value.value.length
    textareaRef.value.selectionEnd = textareaRef.value.value.length
  }
})
</script>
