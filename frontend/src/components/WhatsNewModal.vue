<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="$emit('close')"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl w-[560px] max-w-[calc(100vw-2rem)] mx-4 flex flex-col max-h-[80vh]" @click.stop>
          <div class="px-6 py-4 border-b border-edge flex items-center justify-between flex-none">
            <h3 class="text-lg font-semibold text-content">
              What's New<span v-if="version" class="text-content-tertiary font-normal"> in Stimma {{ version }}</span>
            </h3>
            <button @click="$emit('close')" class="text-content-muted hover:text-content transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="px-6 py-5 overflow-y-auto whats-new-body text-sm text-content-secondary" v-html="renderedNotes"></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderSafeMarkdown } from '../utils/sanitizeHtml'

const props = defineProps<{
  show: boolean
  markdown: string | null
  version: string | null
}>()

defineEmits<{ close: [] }>()

const renderedNotes = computed(() => {
  if (!props.markdown) return ''
  // The notes file opens with "# Release Notes"; the modal header already
  // says it, so drop a leading H1 to avoid a doubled title.
  const body = props.markdown.replace(/^#\s+[^\n]*\n+/, '')
  return renderSafeMarkdown(body, { breaks: false })
})
</script>

<style scoped>
/* Not text-base: this app defines a color named `base`, which wins the
   utility-name collision and turns text-base into background-colored text. */
.whats-new-body :deep(h2) {
  @apply text-content font-semibold text-[16px] mt-5 mb-2 first:mt-0;
}
.whats-new-body :deep(h3) {
  @apply text-content font-medium text-sm mt-4 mb-1.5;
}
.whats-new-body :deep(ul) {
  @apply list-disc pl-5 space-y-1;
}
.whats-new-body :deep(p) {
  @apply mb-2;
}
.whats-new-body :deep(a) {
  @apply text-blue-400 hover:underline;
}
.whats-new-body :deep(code) {
  @apply bg-overlay-subtle px-1 py-0.5 rounded text-[12px];
}
</style>
