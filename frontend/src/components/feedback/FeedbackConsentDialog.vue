<template>
  <Modal
    :show="show"
    size="custom"
    custom-class="w-[520px] max-w-[92vw] max-h-[85vh] flex flex-col overflow-hidden"
    :close-on-backdrop="false"
    :close-on-esc="false"
  >
    <template #header>
      <h2 class="text-base font-semibold text-content">{{ title }}</h2>
    </template>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto px-5 py-4">
      <p class="text-sm text-content-secondary leading-relaxed">{{ bodyText }}</p>
    </div>

    <!-- Footer: one-time consent is primary; persistent consent is explicit. -->
    <template #footer>
      <button
        @click="$emit('dont-send')"
        class="px-3.5 py-2 text-sm text-content-secondary hover:text-content hover:bg-overlay-subtle rounded-lg transition-colors"
      >Don't send</button>
      <button
        @click="$emit('always-send')"
        class="px-3.5 py-2 rounded-lg border border-edge bg-surface hover:bg-overlay-subtle text-content text-sm font-medium transition-colors"
      >Always send</button>
      <button
        @click="$emit('send-once')"
        class="px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-medium rounded-md transition-colors"
      >{{ subject === 'thumbs' ? 'Send this once' : 'Send once' }}</button>
    </template>
  </Modal>
</template>

<script setup>
import { computed } from 'vue'
import Modal from '../ui/Modal.vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  subject: { type: String, default: 'thumbs' }, // 'thumbs' | 'crash'
  /** crash: pending report count for the batched title */
  crashCount: { type: Number, default: 0 },
})

defineEmits(['dont-send', 'send-once', 'always-send'])

const title = computed(() => {
  if (props.subject === 'crash') {
    return props.crashCount > 1
      ? `Send ${props.crashCount} crash reports?`
      : 'Send a crash report?'
  }
  return 'Send this rating?'
})

const bodyText = computed(() => {
  if (props.subject === 'crash') {
    return 'Includes the error, stack trace, and recent log lines, which may contain text from your session.'
  }
  return 'Ratings include the full conversation — messages, prompts, tool calls, and media.'
})

</script>
