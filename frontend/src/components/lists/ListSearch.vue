<script setup lang="ts">
// The search/filter field in a list page header. One look for chats, flows
// and tools. `focusQuietly()` is for focus that happens on page load: the
// field takes focus so typing works at once, but it draws no accent border
// until the person actually interacts (key, click) or focuses it themselves.
import { ref } from 'vue'

defineProps<{
  modelValue: string
  placeholder: string
  ariaLabel?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  escape: []
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const quiet = ref(false)

function focus() {
  quiet.value = false
  inputRef.value?.focus()
}

function focusQuietly() {
  quiet.value = true
  inputRef.value?.focus()
}

function blur() {
  inputRef.value?.blur()
}

defineExpose({ focus, focusQuietly, blur })

function onInput(event: Event) {
  quiet.value = false
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}

function onKeydown(event: KeyboardEvent) {
  quiet.value = false
  if (event.key === 'Escape') emit('escape')
}
</script>

<template>
  <div class="relative">
    <svg class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
    <input
      v-no-autocorrect
      ref="inputRef"
      :value="modelValue"
      type="text"
      :placeholder="placeholder"
      :aria-label="ariaLabel || placeholder"
      class="w-full rounded-md border border-transparent bg-overlay-subtle py-1.5 pl-9 pr-3 text-sm text-content placeholder:text-content-muted focus:outline-none compact:min-h-11"
      :class="quiet ? '' : 'focus:border-accent'"
      @input="onInput"
      @keydown="onKeydown"
      @pointerdown="quiet = false"
      @blur="quiet = false"
    />
  </div>
</template>
