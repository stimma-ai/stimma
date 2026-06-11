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

          <!-- Footer: [Don't send] [Always send ▾ → Send this once] -->
          <div class="flex items-center justify-end gap-3 px-5 py-3.5 border-t border-edge">
            <button
              @click="$emit('dont-send')"
              class="px-3.5 py-2 text-sm text-content-secondary hover:text-content hover:bg-overlay-subtle rounded-lg transition-colors"
            >Don't send</button>
            <div class="relative flex" ref="sendMenuRef">
              <button
                @click="choose('always-send')"
                class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-l-lg transition-colors"
              >Always send</button>
              <button
                @click.stop="sendMenuOpen = !sendMenuOpen"
                class="px-2 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-r-lg border-l border-blue-500 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                </svg>
              </button>
              <div
                v-if="sendMenuOpen"
                class="absolute right-0 bottom-full mb-1 w-44 bg-surface border border-edge-subtle rounded-lg shadow-lg overflow-hidden z-50"
              >
                <button
                  @click="choose('send-once')"
                  class="w-full px-3 py-2 text-left text-sm text-content hover:bg-overlay-light transition-colors"
                >
                  {{ subject === 'thumbs' ? 'Send this once' : 'Send once' }}
                </button>
                <button
                  @click="choose('always-send')"
                  class="w-full px-3 py-2 text-left text-sm text-content bg-blue-600/20 hover:bg-blue-600/30 transition-colors flex items-center justify-between"
                >
                  Always send
                  <span class="text-[10px] text-blue-500">Default</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  subject: { type: String, default: 'thumbs' }, // 'thumbs' | 'crash'
  /** crash: pending report count for the batched title */
  crashCount: { type: Number, default: 0 },
})

const emit = defineEmits(['dont-send', 'send-once', 'always-send'])

const sendMenuOpen = ref(false)
const sendMenuRef = ref(null)

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

function choose(event) {
  sendMenuOpen.value = false
  emit(event)
}

function handleClickOutside(e) {
  if (sendMenuRef.value && !sendMenuRef.value.contains(e.target)) {
    sendMenuOpen.value = false
  }
}

watch(() => props.show, () => {
  sendMenuOpen.value = false
})

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
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
