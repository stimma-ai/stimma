<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10030] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[520px] max-w-[92vw] max-h-[85vh] flex flex-col overflow-hidden">
          <!-- Header -->
          <div class="px-5 py-4 border-b border-edge">
            <h2 class="text-base font-semibold text-content">{{ title }}</h2>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            <p class="text-sm text-content-secondary leading-relaxed">{{ bodyText }}</p>
            <p class="text-xs text-content-tertiary">You can change this anytime in Settings → Privacy.</p>

            <!-- See what will be sent -->
            <details class="rounded-lg border border-edge bg-surface-raised/30">
              <summary
                class="px-3 py-2 text-xs font-medium text-content-secondary cursor-pointer select-none hover:text-content"
                @click="loadPreview"
              >
                See what will be sent
              </summary>
              <div class="px-3 pb-3 space-y-3">
                <!-- Thumbs: conversation package contents -->
                <template v-if="subject === 'thumbs'">
                  <div>
                    <div class="text-[11px] font-medium text-content-tertiary mb-1">Conversation package</div>
                    <div v-if="packagePreview" class="text-xs text-content-secondary">
                      <div v-if="packagePreview.chat_name?.trim()" class="truncate mb-0.5">Name: “{{ packagePreview.chat_name.trim() }}”</div>
                      {{ packagePreview.message_count }} message{{ packagePreview.message_count === 1 ? '' : 's' }}<template v-if="packagePreview.media_ids?.length">,
                      {{ packagePreview.media_ids.length }} media item{{ packagePreview.media_ids.length === 1 ? '' : 's' }}</template>
                      <div v-if="packagePreview.media_ids?.length" class="flex flex-wrap gap-1.5 mt-2">
                        <MediaImage
                          v-for="mid in packagePreview.media_ids.slice(0, 8)"
                          :key="mid"
                          :mediaId="mid"
                          :thumbnail="true"
                          :thumbnailSize="64"
                          containerClass="w-12 h-12 rounded overflow-hidden"
                        />
                        <span
                          v-if="packagePreview.media_ids.length > 8"
                          class="w-12 h-12 rounded bg-surface-raised flex items-center justify-center text-[10px] text-content-muted"
                        >+{{ packagePreview.media_ids.length - 8 }}</span>
                      </div>
                    </div>
                    <div v-else class="text-xs text-content-muted">Loading…</div>
                  </div>
                </template>

                <!-- Crash: pretty-printed reports + log tail -->
                <template v-else>
                  <div v-if="crashPreview === null" class="text-xs text-content-muted">Loading…</div>
                  <template v-else>
                    <div v-for="(report, i) in crashPreview" :key="i">
                      <div class="text-[11px] font-medium text-content-tertiary mb-1">
                        Crash report {{ crashPreview.length > 1 ? i + 1 : '' }} — {{ report.exceptionType }}
                      </div>
                      <pre class="text-[10px] leading-snug text-content-muted bg-surface-raised rounded p-2 max-h-36 overflow-auto whitespace-pre-wrap break-words">{{ formatCrash(report) }}</pre>
                      <details v-if="report.logTail?.length" class="mt-1">
                        <summary class="text-[10px] text-content-muted cursor-pointer">Log tail ({{ report.logTail.length }} lines, secrets redacted)</summary>
                        <pre class="text-[10px] leading-snug text-content-muted bg-surface-raised rounded p-2 max-h-36 overflow-auto whitespace-pre-wrap break-words mt-1">{{ report.logTail.join('\n') }}</pre>
                      </details>
                    </div>
                  </template>
                </template>

                <div class="text-[10px] text-content-muted">
                  Also sent: app version, OS, build channel, and a random install identifier.
                </div>
              </div>
            </details>
          </div>

          <!-- Footer: [Don't send] [Send this once / Send] [Always send] -->
          <div class="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-edge">
            <button
              @click="$emit('dont-send')"
              class="px-3.5 py-2 text-sm text-content-secondary hover:text-content hover:bg-overlay-subtle rounded-lg transition-colors"
            >Don't send</button>
            <button
              @click="$emit('send-once')"
              class="px-3.5 py-2 text-sm font-medium text-content bg-surface-raised hover:bg-surface-hover border border-edge rounded-lg transition-colors"
            >{{ subject === 'thumbs' ? 'Send this once' : 'Send' }}</button>
            <button
              @click="$emit('always-send')"
              class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
            >Always send</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import MediaImage from '../media/MediaImage.vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  subject: { type: String, default: 'thumbs' }, // 'thumbs' | 'crash'
  /** thumbs: the pending package source ({type:'chat', chatId} | {type:'prompt_agent', conversation}) */
  packageSource: { type: Object, default: null },
  /** crash: pending report count for the batched title */
  crashCount: { type: Number, default: 0 },
})

defineEmits(['dont-send', 'send-once', 'always-send'])

const packagePreview = ref(null)
const crashPreview = ref(null)

const title = computed(() => {
  if (props.subject === 'crash') {
    return props.crashCount > 1
      ? `Stimma hit ${props.crashCount} internal errors — send reports?`
      : 'Stimma hit an internal error — send a report?'
  }
  return 'Share this rating with the team?'
})

const bodyText = computed(() => {
  if (props.subject === 'crash') {
    return 'Sending crash reports helps fix problems fast. A report includes the error, a stack trace, and recent log lines — error messages can occasionally include text from your session, so nothing is sent without your OK.'
  }
  return 'Sending feedback helps improve Stimma. Your rating includes this conversation — messages, prompts, tool calls, and generated media — so we can see what happened.'
})

watch(() => props.show, (open) => {
  if (open) {
    packagePreview.value = null
    crashPreview.value = null
  }
})

function formatCrash(report) {
  const { logTail, file, ...rest } = report
  return JSON.stringify(rest, null, 2)
}

async function loadPreview() {
  if (props.subject === 'thumbs') {
    if (packagePreview.value !== null) return
    if (props.packageSource?.type === 'chat') {
      try {
        const { data } = await axios.get(`${getApiBase()}/feedback/package-preview`, {
          params: { chat_id: props.packageSource.chatId },
        })
        packagePreview.value = data
      } catch {
        packagePreview.value = { message_count: 0, media_ids: [] }
      }
    } else if (props.packageSource?.type === 'prompt_agent') {
      const messages = props.packageSource.conversation?.messages || []
      packagePreview.value = { message_count: messages.length, media_ids: [] }
    } else {
      packagePreview.value = { message_count: 0, media_ids: [] }
    }
  } else {
    if (crashPreview.value !== null) return
    try {
      const { data } = await axios.get(`${getApiBase()}/feedback/crashes/preview`)
      crashPreview.value = data.reports || []
    } catch {
      crashPreview.value = []
    }
  }
}
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
