<template>
  <div class="w-full mb-6">
    <!-- Container matching AIPromptEditor style -->
    <div class="p-3 bg-surface-overlay border border-surface-raised rounded-md">
      <!-- Debug Panel (above input) -->
      <div v-if="showDebug" class="mb-3 bg-surface-overlay border border-surface-raised rounded-lg overflow-hidden">
        <div class="max-h-80 overflow-y-auto p-3 space-y-3">
          <div v-if="debugHistory.length === 0" class="text-xs text-content-muted italic py-4 text-center">
            Submit a command to see requests/responses
          </div>
          <div
            v-for="entry in debugHistory"
            :key="entry.id"
            :class="[
              'p-2.5 rounded-lg text-xs relative group',
              entry.type === 'request' ? 'bg-blue-500/10 border border-blue-500/20' :
              entry.type === 'response' ? 'bg-green-500/10 border border-green-500/20' :
              entry.type === 'sam3' ? 'bg-purple-500/10 border border-purple-500/20' :
              'bg-red-500/10 border border-red-500/20'
            ]"
          >
            <!-- Header with type label and delete button -->
            <div class="flex items-center justify-between mb-1.5">
              <span :class="[
                'text-[10px] font-medium uppercase tracking-wide',
                entry.type === 'request' ? 'text-blue-500' :
                entry.type === 'response' ? 'text-green-500' :
                entry.type === 'sam3' ? 'text-purple-500' :
                'text-red-500'
              ]">
                {{ entry.type === 'request' ? '→ Request' :
                   entry.type === 'response' ? '← Response' :
                   entry.type === 'sam3' ? '◆ SAM3' : '✕ Error' }}
              </span>
              <div class="flex items-center gap-2">
                <span class="text-[10px] text-content-muted">{{ formatTimestamp(entry.timestamp) }}</span>
                <button
                  @click="deleteDebugEntry(entry.id)"
                  class="opacity-0 group-hover:opacity-100 text-content-muted hover:text-red-500 transition-all p-0.5"
                  title="Delete this entry"
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
            <!-- Content -->
            <div class="text-content-secondary whitespace-pre-wrap font-mono text-[11px] leading-relaxed">{{ entry.content }}</div>
          </div>
        </div>
        <div class="px-3 py-2 border-t border-surface-raised flex justify-end">
          <button
            @click="clearDebugHistory"
            class="text-[10px] text-content-muted hover:text-red-500 transition-colors"
          >
            Clear all
          </button>
        </div>
      </div>

      <!-- Input row with Apply and Debug buttons -->
      <div class="flex gap-2 items-stretch">
        <input v-no-autocorrect
          ref="inputRef"
          v-model="userInput"
          @keydown.enter="handleSubmit"
          @keydown="handleKeydown"
          type="text"
          placeholder="e.g., mask the lights, unmask the plant, expand, shrink, invert, clear, ..."
          class="flex-1 bg-surface border border-surface-raised rounded-md px-3 py-2 text-sm text-content-secondary placeholder-content-muted focus:outline-none focus:border-accent"
        />
        <button
          @click="handleSubmit"
          :disabled="!userInput.trim()"
          class="px-4 py-2 bg-accent hover:bg-accent/90 text-white rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
        >
          <span v-if="isProcessing" class="flex items-center gap-1.5">
            <div class="w-3 h-3 border-2 border-edge-strong border-t-white rounded-full animate-spin"></div>
            <span v-if="messageQueue.length > 0" class="text-xs opacity-70">+{{ messageQueue.length }}</span>
          </span>
          <span v-else>Apply</span>
        </button>

        <!-- Debug toggle button -->
        <button
          @click="showDebug = !showDebug"
          :class="[
            'px-3 py-2 rounded-md text-sm font-medium transition-colors border',
            showDebug
              ? 'bg-surface-raised text-content border-edge'
              : 'bg-surface text-content-tertiary border-surface-raised hover:text-content hover:border-edge'
          ]"
          title="Show debug log"
        >
          <!-- Bug icon -->
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0112 12.75zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 01-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 002.248-2.354M12 12.75a2.25 2.25 0 01-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 00-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 01.4-2.253M12 8.25a2.25 2.25 0 00-2.248 2.146M12 8.25a2.25 2.25 0 012.248 2.146M8.683 5a6.032 6.032 0 01-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0112 3.75a3.75 3.75 0 013.317 2.002m-.004-.002c.29-.464.49-1.003.574-1.747.054-.527-.077-1.104-.556-1.42a3.744 3.744 0 00-6.662 0c-.479.316-.61.893-.556 1.42.085.744.284 1.283.574 1.747" />
          </svg>
        </button>
      </div>

      <!-- Status/error message -->
      <p v-if="statusMessage" class="mt-2 text-xs" :class="statusMessage.type === 'error' ? 'text-red-500' : 'text-content-muted'">
        {{ statusMessage.text }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

interface Props {
  imagePath: string
  maskEditorRef: any  // Reference to MaskEditor component
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'mask-updated'): void
}>()

// State
const userInput = ref('')
const isProcessing = ref(false)
const showDebug = ref(false)
const inputRef = ref<HTMLInputElement | null>(null)
const messageQueue = ref<string[]>([])

// Command history for up/down arrow navigation
const commandHistory = ref<string[]>([])
const historyIndex = ref(-1)
const tempInput = ref('')  // Store current input when navigating history

interface StatusMessage {
  type: 'info' | 'error' | 'success'
  text: string
}
const statusMessage = ref<StatusMessage | null>(null)

// Conversation history for API context (not displayed)
interface ConversationEntry {
  role: 'user' | 'assistant'
  content: string
}
const conversationHistory = ref<ConversationEntry[]>([])

interface DebugEntry {
  id: number
  type: 'request' | 'response' | 'sam3' | 'error'
  content: string
  timestamp: Date
}
const debugHistory = ref<DebugEntry[]>([])
let debugIdCounter = 0

function addDebugEntry(type: DebugEntry['type'], content: string) {
  debugHistory.value.push({
    id: debugIdCounter++,
    type,
    content,
    timestamp: new Date(),
  })
  // Keep last 50 entries
  if (debugHistory.value.length > 50) {
    debugHistory.value.shift()
  }
}

function deleteDebugEntry(id: number) {
  debugHistory.value = debugHistory.value.filter(e => e.id !== id)
}

function clearDebugHistory() {
  debugHistory.value = []
  conversationHistory.value = []
}

function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString('en-US', { hour12: false })
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (commandHistory.value.length === 0) return

    if (historyIndex.value === -1) {
      // Save current input before navigating
      tempInput.value = userInput.value
      historyIndex.value = commandHistory.value.length - 1
    } else if (historyIndex.value > 0) {
      historyIndex.value--
    }
    userInput.value = commandHistory.value[historyIndex.value]
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (historyIndex.value === -1) return

    if (historyIndex.value < commandHistory.value.length - 1) {
      historyIndex.value++
      userInput.value = commandHistory.value[historyIndex.value]
    } else {
      // Return to the temp input
      historyIndex.value = -1
      userInput.value = tempInput.value
    }
  }
}

async function handleSubmit() {
  const input = userInput.value.trim()
  if (!input) return

  // Add to command history (avoid duplicates at the end)
  if (commandHistory.value[commandHistory.value.length - 1] !== input) {
    commandHistory.value.push(input)
    // Keep last 50 commands
    if (commandHistory.value.length > 50) {
      commandHistory.value.shift()
    }
  }
  // Reset history navigation
  historyIndex.value = -1
  tempInput.value = ''

  userInput.value = ''

  // If already processing, queue the message
  if (isProcessing.value) {
    messageQueue.value.push(input)
    return
  }

  await processMessage(input)
}

async function processMessage(input: string) {
  isProcessing.value = true
  statusMessage.value = null

  // Add to conversation history for API context
  conversationHistory.value.push({ role: 'user', content: input })

  try {
    // Check if mask editor has existing mask
    const hasExistingMask = props.maskEditorRef?.hasMask?.() ?? false
    const defaultExpandPercent = props.maskEditorRef?.expandContractPercent?.value ?? 15

    // Build conversation history for API (excluding current input)
    const apiHistory = conversationHistory.value.slice(0, -1)

    // Step 1: Interpret the command
    addDebugEntry('request', JSON.stringify({
      user_input: input,
      image_path: props.imagePath,
      has_existing_mask: hasExistingMask,
      default_expand_percent: defaultExpandPercent,
      conversation_history: apiHistory,
    }, null, 2))

    const interpretResponse = await axios.post(`${API_BASE}/mask/interpret`, {
      user_input: input,
      image_path: props.imagePath,
      has_existing_mask: hasExistingMask,
      default_expand_percent: defaultExpandPercent,
      conversation_history: apiHistory,
    })

    const result = interpretResponse.data
    addDebugEntry('response', JSON.stringify(result, null, 2))

    // Add LLM response to conversation history for context
    conversationHistory.value.push({ role: 'assistant', content: result.explanation })

    // Step 2: Execute the operation
    if (result.operation === 'clear') {
      // Clear mask
      props.maskEditorRef?.saveToUndoStack?.()
      props.maskEditorRef?.clearMask?.()
      statusMessage.value = { type: 'success', text: 'Mask cleared' }

    } else if (result.operation === 'pad') {
      // Expand/pad mask
      const percent = result.padding?.percent || defaultExpandPercent
      props.maskEditorRef?.expandMask?.(percent)
      statusMessage.value = null

    } else if (result.operation === 'contract') {
      // Contract/shrink mask
      const percent = result.padding?.percent || defaultExpandPercent
      props.maskEditorRef?.contractMask?.(percent)
      statusMessage.value = null

    } else if (result.operation === 'invert') {
      // Invert mask
      props.maskEditorRef?.invertMask?.()
      statusMessage.value = null

    } else if (result.sam3_commands && result.sam3_commands.length > 0) {
      // Run SAM3 segmentation for each command
      const isAdd = result.operation === 'add'
      const isUnmask = result.operation === 'unmask'

      // Save undo state before modifying (subtractMaskFromDataUrl does its own save)
      if (!isUnmask) {
        props.maskEditorRef?.saveToUndoStack?.()
      }

      let successCount = 0
      for (const cmd of result.sam3_commands) {
        const isPlural = cmd.is_plural ?? false
        addDebugEntry('sam3', `Segmenting: "${cmd.prompt}" (confidence: ${cmd.confidence}, plural: ${isPlural})`)

        try {
          const segmentResponse = await axios.post(`${API_BASE}/mask/segment`, {
            image_path: props.imagePath,
            prompt: cmd.prompt,
            confidence: cmd.confidence,
            return_all_above_threshold: isPlural,
            threshold: 0.7,
          })

          const segResult = segmentResponse.data
          addDebugEntry('sam3', `Result: ${segResult.success ? 'success' : 'failed'} - ${segResult.detections_count} detections, best confidence: ${segResult.best_confidence?.toFixed(2) || 'N/A'}`)

          if (segResult.success) {
            // For plural queries, apply all masks
            const masksToApply = isPlural && segResult.mask_data_urls?.length > 0
              ? segResult.mask_data_urls
              : segResult.mask_data_url ? [segResult.mask_data_url] : []

            for (const maskUrl of masksToApply) {
              if (isUnmask) {
                // Use subtract with 80% overlap greedy removal
                await props.maskEditorRef?.subtractMaskFromDataUrl?.(maskUrl)
              } else {
                const operation = (isAdd || successCount > 0) ? 'add' : 'replace'
                await props.maskEditorRef?.applyMaskFromDataUrl?.(maskUrl, operation)
              }
              successCount++
            }
          } else {
            addDebugEntry('error', `SAM3 failed for "${cmd.prompt}": ${segResult.error || 'No mask data'}`)
          }
        } catch (err: any) {
          addDebugEntry('error', `SAM3 request failed: ${err.message}`)
        }
      }

      if (successCount > 0) {
        statusMessage.value = null
        emit('mask-updated')
      } else {
        statusMessage.value = { type: 'error', text: 'No regions found' }
      }

    } else {
      statusMessage.value = { type: 'info', text: result.explanation }
    }

  } catch (err: any) {
    console.error('AI mask assistant error:', err)
    addDebugEntry('error', err.response?.data?.detail || err.message)
    statusMessage.value = { type: 'error', text: err.response?.data?.detail || 'Failed to process command' }

    // Add error to conversation history
    conversationHistory.value.push({ role: 'assistant', content: `Error: ${err.response?.data?.detail || err.message}` })
  } finally {
    isProcessing.value = false
    // Focus input for next command
    inputRef.value?.focus()

    // Process next queued message if any
    if (messageQueue.value.length > 0) {
      const nextMessage = messageQueue.value.shift()!
      await processMessage(nextMessage)
    }
  }
}
</script>
