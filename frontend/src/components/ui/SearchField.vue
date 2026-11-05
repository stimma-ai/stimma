<script setup lang="ts">
// The one search/filter field (DESIGN.md §2). Fill-only (§1.4): a faint fill,
// no outline at rest, an accent border once the person is typing in it.
// `focusQuietly()` is for focus that happens on page load: the field takes
// focus so typing works at once, but draws no accent border until the person
// interacts (key, click) or focuses it themselves.
import { ref } from 'vue'
import { MagnifyingGlassIcon } from '@heroicons/vue/24/outline'

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
    <MagnifyingGlassIcon class="pointer-events-none absolute left-3 top-1/2 h-icon-nav w-icon-nav -translate-y-1/2 text-content-muted" aria-hidden="true" />
    <input
      v-no-autocorrect
      ref="inputRef"
      :value="modelValue"
      type="text"
      :placeholder="placeholder"
      :aria-label="ariaLabel || placeholder"
      class="w-full rounded-md border border-transparent bg-overlay-subtle py-1.5 pl-9 pr-3 text-sm text-content placeholder:text-content-muted focus:outline-none coarse:min-h-11"
      :class="quiet ? '' : 'focus:border-accent'"
      @input="onInput"
      @keydown="onKeydown"
      @pointerdown="quiet = false"
      @blur="quiet = false"
    />
  </div>
</template>
