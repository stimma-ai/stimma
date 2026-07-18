<template>
  <button
    @click.stop="sendThumb('up')"
    :disabled="!thumbsEnabled"
    class="ml-0.5 p-0.5 rounded transition-colors"
    :class="thumbsEnabled
      ? 'text-content-muted hover:text-accent hover:bg-accent/10'
      : 'text-content-muted/40 cursor-default'"
    :title="thumbsDisabledReason || 'Good response - send feedback'"
  >
    <HandThumbUpIcon class="h-3 w-3" />
  </button>
  <button
    @click.stop="sendThumb('down')"
    :disabled="!thumbsEnabled"
    class="p-0.5 rounded transition-colors"
    :class="thumbsEnabled
      ? 'text-content-muted hover:text-red-500 hover:bg-red-500/10'
      : 'text-content-muted/40 cursor-default'"
    :title="thumbsDisabledReason || 'Bad response - send feedback'"
  >
    <HandThumbDownIcon class="h-3 w-3" />
  </button>
</template>

<script setup>
import { HandThumbUpIcon, HandThumbDownIcon } from '@heroicons/vue/24/outline'
import { useFeedback } from '../../composables/useFeedback'

const props = defineProps({
  packageSource: {
    type: Function,
    required: true,
  },
})

const { openThumbFeedback, thumbsEnabled, thumbsDisabledReason } = useFeedback()

function sendThumb(thumb) {
  if (!thumbsEnabled.value) return
  openThumbFeedback({
    thumb,
    agentContext: 'prompt-agent',
    packageSource: { type: 'prompt_agent', conversation: props.packageSource() },
  })
}
</script>
