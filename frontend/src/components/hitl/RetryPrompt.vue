<template>
  <div class="retry-prompt">
    <div class="flex items-start gap-3">
      <ExclamationTriangleIcon class="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
      <div class="flex-1 min-w-0">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs font-medium text-amber-500">Execution Error</span>
          <button
            v-if="errorMessage"
            @click="showRaw = !showRaw"
            class="text-[11px] uppercase tracking-wide transition-colors select-none"
            :class="showRaw ? 'text-blue-400' : 'text-content-muted/40 hover:text-content-muted'"
          >
            Raw
          </button>
        </div>
        <!-- Summary view (markdown rendered) -->
        <div v-if="!showRaw" class="text-sm text-content-secondary prose prose-sm max-w-none" v-html="renderedPrompt"></div>
        <!-- Raw error view -->
        <div v-else class="text-xs text-content-muted font-mono whitespace-pre-wrap break-all leading-relaxed">{{ errorMessage }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { ExclamationTriangleIcon } from '@heroicons/vue/24/outline'

const props = defineProps({
  prompt: {
    type: String,
    required: true
  },
  errorMessage: {
    type: String,
    default: null
  },
  errorSummary: {
    type: String,
    default: null
  },
  failedNodeId: {
    type: String,
    default: null
  }
})

defineEmits(['respond'])

const showRaw = ref(false)

const displayPrompt = computed(() => {
  if (props.errorSummary) {
    return props.prompt
  }
  return props.prompt.replace(/\n\n.*would you like to.*/is, '').trim()
})

const renderedPrompt = computed(() => {
  if (!displayPrompt.value) return ''
  return marked.parse(displayPrompt.value, { breaks: true })
})
</script>
