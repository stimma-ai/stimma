<template>
  <div class="fixed inset-0 bg-black/80 flex items-center justify-center z-[10000] p-8" @click.self="close">
    <div class="bg-surface border border-edge rounded-xl w-full max-w-[900px] max-h-[85vh] flex flex-col shadow-[0_20px_25px_-5px_rgba(0,0,0,0.5)]">
      <div class="flex justify-between items-center px-6 py-4 border-b border-edge">
        <h2 class="m-0 text-lg font-semibold text-content">{{ title }}</h2>
        <button
          class="bg-transparent border-none text-content-tertiary cursor-pointer p-2 flex items-center justify-center rounded transition-all hover:bg-overlay-light hover:text-content"
          @click="close"
        >
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="flex-1 p-6 overflow-hidden flex flex-col">
        <textarea
          ref="textareaRef"
          v-model="localValue"
          :placeholder="placeholder"
          class="flex-1 w-full min-h-[450px] bg-surface text-content text-sm border border-edge rounded-lg px-4 py-3 focus:outline-none focus:border-blue-500 resize-none"
        />
        <p v-if="hint" class="text-xs text-content-muted mt-3 leading-relaxed">
          {{ hint }}
        </p>
      </div>

      <div class="px-6 py-4 border-t border-edge flex justify-end gap-3">
        <button
          class="bg-surface-raised text-content border-none py-2.5 px-6 rounded-lg text-sm font-medium cursor-pointer transition-all hover:bg-surface-hover"
          @click="close"
        >
          Cancel
        </button>
        <button
          class="bg-blue-600 text-white border-none py-2.5 px-6 rounded-lg text-sm font-medium cursor-pointer transition-all hover:bg-blue-500"
          @click="save"
        >
          Save
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'

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
