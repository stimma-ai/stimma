<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10030] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[520px] max-w-[92vw] max-h-[85vh] flex flex-col">
          <!-- Header -->
          <div class="px-5 py-4 border-b border-edge">
            <h2 class="text-base font-semibold text-content">{{ title }}</h2>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-4">
            <p class="text-sm text-content-secondary leading-relaxed">{{ bodyText }}</p>
          </div>

          <!-- Footer: one-time consent is primary; persistent consent is explicit. -->
          <div class="flex items-center justify-end gap-3 px-5 py-3.5 border-t border-edge">
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
              class="px-4 py-2 bg-blue-500 hover:bg-blue-400 text-white text-sm font-medium rounded-lg transition-colors"
            >{{ subject === 'thumbs' ? 'Send this once' : 'Send once' }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'

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

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
