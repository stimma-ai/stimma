<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="close"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl max-w-2xl w-full mx-4">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-edge flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 text-red-500">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
                </svg>
              </div>
              <h3 class="text-lg font-semibold text-content">Job Failed</h3>
            </div>
            <button
              @click="close"
              class="text-content-tertiary hover:text-content transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="px-6 py-4 space-y-4 select-text">
            <!-- Error Message -->
            <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
              <div class="flex items-center justify-between mb-1">
                <div class="text-xs text-red-500 uppercase font-semibold">Error</div>
                <button
                  @click="copyError"
                  class="text-red-500 hover:text-red-600 transition-colors p-1 -m-1"
                  title="Copy error"
                >
                  <svg v-if="!copied" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
                  </svg>
                  <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 text-green-500">
                    <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                  </svg>
                </button>
              </div>
              <div class="text-red-500 text-sm font-mono break-words">{{ job?.error || 'Unknown error' }}</div>
            </div>

            <!-- Job Details -->
            <div class="space-y-3">
              <div class="flex justify-between text-sm">
                <span class="text-content-tertiary">Job ID</span>
                <span class="text-content font-mono">#{{ job?.id }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-content-tertiary">Tool</span>
                <span class="text-content">{{ job?.model_name || 'N/A' }}</span>
              </div>
              <div v-if="params?.width && params?.height" class="flex justify-between text-sm">
                <span class="text-content-tertiary">Dimensions</span>
                <span class="text-content">{{ params.width }} × {{ params.height }}</span>
              </div>
              <div v-if="params?.seed" class="flex justify-between text-sm">
                <span class="text-content-tertiary">Seed</span>
                <span class="text-content font-mono">{{ params.seed }}</span>
              </div>
              <div v-if="job?.created_at" class="flex justify-between text-sm">
                <span class="text-content-tertiary">Submitted</span>
                <span class="text-content">{{ formatTime(job.created_at) }}</span>
              </div>
            </div>

            <!-- Prompt (collapsible if long) -->
            <div v-if="params?.prompt">
              <div class="text-xs text-content-tertiary uppercase font-semibold mb-2">Prompt</div>
              <div class="bg-base rounded-lg p-3 text-sm text-content-secondary max-h-32 overflow-y-auto">
                {{ params.prompt }}
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 border-t border-edge flex gap-3 justify-end">
            <button
              @click="retry"
              class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium flex items-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
              </svg>
              Retry
            </button>
            <button
              @click="dismiss"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { copyToClipboard } from '../../utils/clipboard'

interface Job {
  id: number
  status: string
  model_name?: string
  error?: string
  parameters?: string
  created_at?: string
}

const props = defineProps<{
  show: boolean
  job: Job | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'retry', jobId: number): void
  (e: 'dismiss', jobId: number): void
}>()

const copied = ref(false)

async function copyError() {
  const errorText = props.job?.error || 'Unknown error'
  const success = await copyToClipboard(errorText)
  if (success) {
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  }
}

const params = computed(() => {
  if (!props.job?.parameters) return null
  try {
    return JSON.parse(props.job.parameters)
  } catch {
    return null
  }
})

function formatTime(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleString()
}

function close() {
  emit('close')
}

function retry() {
  if (props.job) {
    emit('retry', props.job.id)
  }
}

function dismiss() {
  if (props.job) {
    emit('dismiss', props.job.id)
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

.modal-enter-active .bg-surface,
.modal-leave-active .bg-surface {
  transition: transform 0.15s ease;
}

.modal-enter-from .bg-surface,
.modal-leave-to .bg-surface {
  transform: scale(0.95);
}
</style>
