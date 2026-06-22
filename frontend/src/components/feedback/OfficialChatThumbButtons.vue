<template>
  <button
    @click.stop="sendThumb('up')"
    :disabled="!thumbsEnabled"
    class="p-1 rounded transition-colors"
    :class="thumbsEnabled
      ? 'text-content-muted hover:text-blue-500 hover:bg-blue-500/10'
      : 'text-content-muted/40 cursor-default'"
    :title="thumbsDisabledReason || 'Good response - send feedback'"
  >
    <HandThumbUpIcon class="w-3.5 h-3.5" />
  </button>
  <button
    @click.stop="sendThumb('down')"
    :disabled="!thumbsEnabled"
    class="p-1 rounded transition-colors"
    :class="thumbsEnabled
      ? 'text-content-muted hover:text-red-500 hover:bg-red-500/10'
      : 'text-content-muted/40 cursor-default'"
    :title="thumbsDisabledReason || 'Bad response - send feedback'"
  >
    <HandThumbDownIcon class="w-3.5 h-3.5" />
  </button>
</template>

<script setup>
import { HandThumbUpIcon, HandThumbDownIcon } from '@heroicons/vue/24/outline'
import { useFeedback } from '../../composables/useFeedback'

const props = defineProps({
  agentContext: {
    type: String,
    default: 'main',
  },
  packageSource: {
    type: Object,
    required: true,
  },
})

const { openThumbFeedback, thumbsEnabled, thumbsDisabledReason } = useFeedback()

function sendThumb(thumb) {
  if (!thumbsEnabled.value) return
  openThumbFeedback({
    thumb,
    agentContext: props.agentContext,
    packageSource: props.packageSource,
  })
}
</script>
