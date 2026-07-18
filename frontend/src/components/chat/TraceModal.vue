<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="close"
      >
        <div class="bg-surface border border-edge rounded-lg shadow-2xl max-w-4xl w-full mx-4 max-h-[85vh] flex flex-col">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-edge flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <!-- Back button when viewing detail -->
              <button
                v-if="selectedTraceId"
                @click="selectedTraceId = null"
                class="p-1 -ml-1 rounded hover:bg-surface-raised/50 text-content-tertiary hover:text-content transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
                  <path fill-rule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clip-rule="evenodd" />
                </svg>
              </button>
              <div class="w-8 h-8 rounded-full bg-purple-500/20 flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 text-purple-500">
                  <path fill-rule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v11.5A2.25 2.25 0 004.25 18h11.5A2.25 2.25 0 0018 15.75V4.25A2.25 2.25 0 0015.75 2H4.25zM15 5.75a.75.75 0 00-1.5 0v8.5a.75.75 0 001.5 0v-8.5zm-8.5 6a.75.75 0 00-1.5 0v2.5a.75.75 0 001.5 0v-2.5zM8.584 9a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5a.75.75 0 01.75-.75zm3.58-1.25a.75.75 0 00-1.5 0v6.5a.75.75 0 001.5 0v-6.5z" clip-rule="evenodd" />
                </svg>
              </div>
              <div>
                <h3 class="text-lg font-semibold text-content">
                  {{ selectedTraceId ? 'LLM Trace' : (toolCallId ? 'Delegate Agent Traces' : 'Sub-Agent Traces') }}
                </h3>
                <p v-if="selectedTraceId && trace" class="text-xs text-content-tertiary">
                  {{ traceTypeLabel }}
                  <span v-if="trace.model" class="text-content-muted">· {{ trace.model }}</span>
                </p>
                <p v-else-if="!selectedTraceId" class="text-xs text-content-tertiary">
                  {{ toolCallId ? 'LLM conversation at each turn of the delegate subagent' : 'Debug LLM calls from planner, prompt crafter, and reference resolver' }}
                </p>
              </div>
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
          <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            <!-- Loading state -->
            <div v-if="loading" class="flex items-center justify-center py-12">
              <svg class="w-6 h-6 animate-spin text-content-tertiary" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-opacity="0.3"/>
                <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
              </svg>
            </div>

            <!-- Error state -->
            <div v-else-if="error" class="text-red-500 text-sm py-8 text-center">
              {{ error }}
            </div>

            <!-- List view (no trace selected) -->
            <template v-else-if="!selectedTraceId">
              <div v-if="traceList.length === 0" class="text-content-muted text-sm py-8 text-center">
                No traces found for this chat.
              </div>
              <div v-else class="space-y-2">
                <button
                  v-for="t in traceList"
                  :key="t.id"
                  @click="selectedTraceId = t.id"
                  class="w-full text-left px-4 py-3 rounded-lg border transition-colors"
                  :class="getTraceListItemClasses(t.trace_type)"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                      <component :is="getTraceIcon(t.trace_type)" class="w-5 h-5" :class="getTraceIconColor(t.trace_type)" />
                      <div>
                        <div class="font-medium text-sm" :class="getTraceTextColor(t.trace_type)">
                          {{ traceTypeLabels[t.trace_type] || t.trace_type }}
                        </div>
                        <div class="text-xs text-content-muted">
                          {{ t.model || 'unknown model' }} · {{ t.message_count }} msgs
                          <span v-if="t.est_tokens" class="text-content-tertiary">· ~{{ formatTokens(t.est_tokens) }} tokens</span>
                        </div>
                      </div>
                    </div>
                    <div class="text-xs text-content-muted">
                      {{ formatTime(t.created_at) }}
                    </div>
                  </div>
                </button>
              </div>
            </template>

            <!-- Detail view (trace selected) -->
            <template v-else-if="trace">
              <!-- Messages -->
              <div class="space-y-3">
                <h4 class="text-xs font-semibold text-content-secondary">Messages sent to LLM</h4>
                <div
                  v-for="(msg, i) in trace.messages"
                  :key="i"
                  class="rounded-lg border overflow-hidden"
                  :class="getMessageClasses(msg.role)"
                >
                  <!-- Message header -->
                  <div
                    class="flex items-center justify-between px-3 py-2 cursor-pointer"
                    :class="getMessageHeaderBg(msg.role)"
                    @click="toggleMessage(i)"
                  >
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-semibold uppercase" :class="getMessageRoleColor(msg.role)">
                        {{ msg.role }}
                      </span>
                      <span class="text-xs text-content-muted">
                        {{ formatContentLength(msg.content) }}
                      </span>
                    </div>
                    <svg
                      class="w-4 h-4 text-content-muted transition-transform"
                      :class="{ 'rotate-180': expandedMessages[i] }"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                    </svg>
                  </div>
                  <!-- Message content (collapsible) -->
                  <div
                    v-if="expandedMessages[i]"
                    class="px-3 py-2 bg-surface-overlay max-h-[400px] overflow-y-auto"
                  >
                    <pre class="text-xs text-content-secondary whitespace-pre-wrap break-words font-mono leading-relaxed select-text">{{ formatContent(msg.content) }}</pre>
                  </div>
                </div>
              </div>

              <!-- Response -->
              <div class="space-y-3">
                <h4 class="text-xs font-semibold text-content-secondary">Raw LLM response</h4>
                <div class="rounded-lg border border-emerald-500/30 overflow-hidden">
                  <div
                    class="flex items-center justify-between px-3 py-2 bg-emerald-500/10 cursor-pointer"
                    @click="responseExpanded = !responseExpanded"
                  >
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-semibold uppercase text-emerald-500">response</span>
                      <span class="text-xs text-content-muted">
                        {{ formatContentLength(trace.response) }}
                      </span>
                    </div>
                    <svg
                      class="w-4 h-4 text-content-muted transition-transform"
                      :class="{ 'rotate-180': responseExpanded }"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                    </svg>
                  </div>
                  <div
                    v-if="responseExpanded"
                    class="px-3 py-2 bg-surface-overlay max-h-[400px] overflow-y-auto"
                  >
                    <pre class="text-xs text-content-secondary whitespace-pre-wrap break-words font-mono leading-relaxed select-text">{{ formatContent(trace.response) }}</pre>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 border-t border-edge flex gap-3 justify-end shrink-0">
            <button
              v-if="selectedTraceId && trace"
              @click="copyTrace"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium flex items-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z" />
                <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z" />
              </svg>
              {{ copied ? 'Copied!' : 'Copy All' }}
            </button>
            <button
              @click="close"
              class="px-4 py-2 bg-accent hover:bg-accent/90 text-white rounded-md font-medium"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, h } from 'vue'
import {
  ClipboardDocumentListIcon,
  DocumentTextIcon,
  LinkIcon,
  CpuChipIcon,
  UserGroupIcon
} from '@heroicons/vue/24/outline'
import { copyToClipboard } from '../../utils/clipboard'
import { useTheme } from '../../composables/useTheme'

const { resolvedTheme } = useTheme()
const isLight = computed(() => resolvedTheme.value === 'light')

interface TraceMessage {
  role: string
  content: string
}

interface TraceListItem {
  id: number
  trace_type: string
  node_id?: string
  tool_call_id?: string
  model?: string
  created_at: string
  message_count: number
}

interface Trace {
  id: number
  trace_type: string
  node_id?: string
  tool_call_id?: string
  messages: TraceMessage[]
  response?: string
  model?: string
  created_at: string
}

const props = defineProps<{
  show: boolean
  chatId: number | null
  traceId?: number | null  // Optional: if provided, go directly to detail view
  planId?: string | null   // Optional: filter traces by plan ID
  toolCallId?: string | null  // Optional: filter traces by tool_call_id (for delegate subagent traces)
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const traceList = ref<TraceListItem[]>([])
const selectedTraceId = ref<number | null>(null)
const trace = ref<Trace | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const copied = ref(false)
const expandedMessages = ref<Record<number, boolean>>({})
const responseExpanded = ref(true)

const traceTypeLabels: Record<string, string> = {
  'main_agent': 'Main Agent',
  'planner': 'Planner',  // legacy
  'prompt_craft': 'Prompt Crafter',
  'resolve_reference': 'Reference Resolver',
  'delegate': 'Delegate Agent',
}

const traceTypeLabel = computed(() => {
  if (!trace.value) return ''
  return traceTypeLabels[trace.value.trace_type] || trace.value.trace_type
})

// Fetch trace list when modal opens
watch([() => props.show, () => props.chatId, () => props.planId, () => props.toolCallId], async () => {
  if (!props.show || !props.chatId) {
    return
  }

  // Reset state
  traceList.value = []
  selectedTraceId.value = props.traceId || null
  trace.value = null
  error.value = null

  // If traceId provided, go directly to detail
  if (props.traceId) {
    await fetchTraceDetail(props.traceId)
    return
  }

  // Otherwise fetch list (optionally filtered by plan_id or tool_call_id)
  loading.value = true
  try {
    let url = `/api/chats/${props.chatId}/traces`
    const params = new URLSearchParams()
    if (props.planId) params.set('plan_id', props.planId)
    if (props.toolCallId) params.set('tool_call_id', props.toolCallId)
    if (params.toString()) url += `?${params.toString()}`
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error('Failed to fetch traces')
    }
    const data = await response.json()
    traceList.value = data.items || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Unknown error'
  } finally {
    loading.value = false
  }
}, { immediate: true })

// Fetch trace detail when selected
watch(() => selectedTraceId.value, async (newId) => {
  if (!newId || !props.chatId) {
    trace.value = null
    return
  }
  await fetchTraceDetail(newId)
})

async function fetchTraceDetail(traceId: number) {
  loading.value = true
  error.value = null
  trace.value = null
  expandedMessages.value = {}
  responseExpanded.value = true

  try {
    const response = await fetch(`/api/chats/${props.chatId}/traces/${traceId}`)
    if (!response.ok) {
      throw new Error('Failed to fetch trace')
    }
    trace.value = await response.json()

    // Auto-expand user message, collapse system (since it's usually large)
    if (trace.value?.messages) {
      trace.value.messages.forEach((msg, i) => {
        expandedMessages.value[i] = msg.role !== 'system'
      })
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Unknown error'
  } finally {
    loading.value = false
  }
}

function toggleMessage(index: number) {
  expandedMessages.value[index] = !expandedMessages.value[index]
}

function getTraceIcon(traceType: string) {
  switch (traceType) {
    case 'main_agent': return CpuChipIcon
    case 'planner': return ClipboardDocumentListIcon  // legacy
    case 'prompt_craft': return DocumentTextIcon
    case 'resolve_reference': return LinkIcon
    case 'delegate': return UserGroupIcon
    default: return DocumentTextIcon
  }
}

function getTraceListItemClasses(traceType: string) {
  const light = isLight.value
  switch (traceType) {
    case 'main_agent': return light ? 'border-blue-500/40 bg-blue-500/10 hover:bg-blue-500/15' : 'border-blue-500/30 bg-blue-500/5 hover:bg-blue-500/10'
    case 'planner': return light ? 'border-blue-500/40 bg-blue-500/10 hover:bg-blue-500/15' : 'border-blue-500/30 bg-blue-500/5 hover:bg-blue-500/10'  // legacy
    case 'prompt_craft': return light ? 'border-purple-500/40 bg-purple-500/10 hover:bg-purple-500/15' : 'border-purple-500/30 bg-purple-500/5 hover:bg-purple-500/10'
    case 'resolve_reference': return light ? 'border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/15' : 'border-amber-500/30 bg-amber-500/5 hover:bg-amber-500/10'
    case 'delegate': return light ? 'border-orange-500/40 bg-orange-500/10 hover:bg-orange-500/15' : 'border-orange-500/30 bg-orange-500/5 hover:bg-orange-500/10'
    default: return 'border-edge/50 bg-surface/50 hover:bg-surface-raised/50'
  }
}

function getTraceIconColor(traceType: string) {
  const light = isLight.value
  switch (traceType) {
    case 'main_agent': return light ? 'text-blue-600' : 'text-blue-500'
    case 'planner': return light ? 'text-blue-600' : 'text-blue-500'  // legacy
    case 'prompt_craft': return light ? 'text-purple-600' : 'text-purple-500'
    case 'resolve_reference': return light ? 'text-amber-600' : 'text-amber-500'
    case 'delegate': return light ? 'text-orange-600' : 'text-orange-500'
    default: return 'text-content-tertiary'
  }
}

function getTraceTextColor(traceType: string) {
  const light = isLight.value
  switch (traceType) {
    case 'main_agent': return light ? 'text-blue-700' : 'text-blue-500'
    case 'planner': return light ? 'text-blue-700' : 'text-blue-500'  // legacy
    case 'prompt_craft': return light ? 'text-purple-700' : 'text-purple-500'
    case 'resolve_reference': return light ? 'text-amber-700' : 'text-amber-500'
    case 'delegate': return light ? 'text-orange-700' : 'text-orange-500'
    default: return 'text-content-secondary'
  }
}

function getMessageClasses(role: string) {
  switch (role) {
    case 'system': return 'border-purple-500/30'
    case 'user': return 'border-blue-500/30'
    case 'assistant': return 'border-emerald-500/30'
    default: return 'border-edge/50'
  }
}

function getMessageHeaderBg(role: string) {
  switch (role) {
    case 'system': return 'bg-purple-500/10'
    case 'user': return 'bg-blue-500/10'
    case 'assistant': return 'bg-emerald-500/10'
    default: return 'bg-surface-raised/30'
  }
}

function getMessageRoleColor(role: string) {
  switch (role) {
    case 'system': return 'text-purple-500'
    case 'user': return 'text-blue-500'
    case 'assistant': return 'text-emerald-500'
    default: return 'text-content-tertiary'
  }
}

function formatContentLength(content: string | undefined | null): string {
  if (!content) return '(empty)'
  const chars = content.length
  if (chars < 1000) return `${chars} chars`
  return `${(chars / 1000).toFixed(1)}k chars`
}

function formatTokens(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function formatContent(content: string | undefined | null): string {
  if (!content) return '(empty)'
  return content
}

function formatTime(isoString: string): string {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function close() {
  emit('close')
}

async function copyTrace() {
  if (!trace.value) return

  const data = {
    trace_type: trace.value.trace_type,
    model: trace.value.model,
    messages: trace.value.messages,
    response: trace.value.response
  }

  const success = await copyToClipboard(JSON.stringify(data, null, 2))
  if (success) {
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
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
