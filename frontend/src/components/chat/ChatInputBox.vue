<template>
  <div
    class="relative"
    @dragover.prevent="onDragOver"
    @dragenter.prevent="onDragOver"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- Drop overlay -->
    <Transition name="fade">
      <div
        v-if="dragging && !agentUnavailable"
        class="pointer-events-none absolute inset-0 bg-accent/10 backdrop-blur-sm z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-accent/50"
      >
        <div class="flex flex-col items-center gap-2 text-accent">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-10 h-10">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
          </svg>
          <span class="text-sm font-medium">Drop asset here</span>
        </div>
      </div>
    </Transition>

    <!-- Composer shell. Fill-only (DESIGN.md 1.4): one background step, no
         hairline. Three explicit looks: resting (fill alone, the same on every
         layout), focused (a quiet accent ring, only while the person has really
         focused it) and contextual (attached under a tray, squared on top).
         Focus the page gives it on load stays quiet until the person types or
         clicks, as in ListSearch. Meta line, placeholder and model picker all
         start at one left edge (16px). -->
    <div
      class="bg-field overflow-hidden transition-shadow duration-150"
      :class="[
        attachedTop ? 'rounded-b-lg border-t border-edge-subtle' : 'rounded-lg',
        ringVisible ? 'ring-1 ring-accent/40' : '',
      ]"
      data-composer-shell
      :data-composer-state="attachedTop ? 'contextual' : ringVisible ? 'focused' : 'resting'"
      @focusin="hasFocus = true"
      @focusout="onShellFocusOut"
      @pointerdown="quiet = false"
      @keydown="quiet = false"
    >
      <!-- Optional header above attachments — used by FlowView to render
           the context-reference tray. The unavailable state replaces the
           whole typing region, including empty context. -->
      <slot v-if="!agentUnavailable" name="context-header" />

      <div v-if="context && !agentUnavailable" class="mx-4 truncate pt-3 text-[11px] leading-4 text-content-muted" data-composer-context>{{ context }}</div>

      <!-- Attachments preview -->
      <ChatInputAttachments
        v-if="!agentUnavailable && attachments.length > 0"
        :attachments="attachments"
        @remove="removeAttachment"
      />

      <AgentUnavailableInput v-if="agentUnavailable" />

      <!-- The textarea owns scrolling so the browser can keep its caret visible. -->
      <div v-else class="mx-4 coarse:mt-0"
        :class="context ? 'mt-1.5' : 'mt-3'">
        <textarea v-no-autocorrect
          ref="textareaRef"
          :value="inputText"
          @input="setText($event.target.value)"
          :placeholder="placeholder"
          :rows="rows"
          class="chat-input-textarea w-full bg-transparent text-content p-0 coarse:py-2.5 focus:outline-none resize-none block overflow-y-auto"
          @keydown.enter.exact.prevent="$emit('submit')"
          @keydown="onTextareaKeydown"
          @keyup="onTextareaKeyup"
        />
      </div>

      <!-- Action bar: two groups, the model on the left and the utilities with
           send on the right. The utilities (attach, skills, voice) are one
           cluster; send stands apart from it. -->
      <div
        class="flex items-center justify-between gap-3 px-2 pb-2 pt-2 coarse:pb-1.5 coarse:pt-1"
        :class="agentUnavailable ? 'border-t border-edge-subtle' : ''"
      >
        <!-- Left: model picker -->
        <div class="flex min-w-0 items-center">
          <div v-if="agentUnavailable" class="pointer-events-none opacity-50">
            <slot name="model-picker" />
          </div>
          <slot v-else name="model-picker" />
        </div>

        <div class="flex flex-none items-center gap-3">
          <!-- Utilities: attach, extra toolbar controls (the skills menu), voice -->
          <div class="flex items-center gap-0.5">
            <button
              :disabled="agentUnavailable"
              @click="openUploadPicker"
              class="w-8 h-8 coarse:w-11 coarse:h-11 flex items-center justify-center rounded-md text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors disabled:pointer-events-none disabled:opacity-50"
              title="Add image"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-icon-nav h-icon-nav">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
            </button>
            <slot v-if="!agentUnavailable" name="toolbar-extra" />
            <button
              v-if="agentUnavailable"
              type="button"
              disabled
              class="flex h-8 w-8 items-center justify-center rounded-md text-content-muted opacity-50"
              title="Voice input unavailable"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="h-icon-nav w-icon-nav">
                <rect x="9" y="3" width="6" height="12" rx="3" />
                <path stroke-linecap="round" d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6" />
              </svg>
            </button>
            <VoiceInputButton v-else ref="voiceBtn" :get-text="getText" :set-text="setText" :focus="focusTextarea" :surface="voiceSurface" />
          </div>

          <!-- Right: slot for custom buttons, or default send -->
          <SendButton v-if="agentUnavailable" disabled title="Send unavailable" />
          <slot v-else name="actions" :text="inputText">
            <SendButton
              title="Send"
              :disabled="(!inputText.trim() && attachments.length === 0) || disabled"
              @click="$emit('submit')"
            />
          </slot>
        </div>
      </div>
    </div>

    <!-- Hidden file input -->
    <input
      ref="uploadInputRef"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      :disabled="agentUnavailable"
      @change="handleUploadSelect"
    />
  </div>
</template>

<script setup>
import { addToast, reportActionError } from '../../composables/useToasts'
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'
import ChatInputAttachments from './ChatInputAttachments.vue'
import VoiceInputButton from '../voice/VoiceInputButton.vue'
import AgentUnavailableInput from './AgentUnavailableInput.vue'
import SendButton from '../ui/SendButton.vue'
import { useOwnerProject } from '../../composables/useProjectScope'
import { appendProjectId } from '../../utils/projectScope'

const props = defineProps({
  modelValue: { type: String, default: '' },
  // Optional shared draft: only the composer reads its text during rendering.
  // The host can read/write it in event handlers without rendering history on
  // every keystroke. Existing v-model consumers retain their usual behavior.
  draft: { type: Object, default: null },
  placeholder: { type: String, default: 'Type a message...' },
  // Something (the message queue) is docked on top; square the top corners.
  attachedTop: { type: Boolean, default: false },
  rows: { type: Number, default: 1 },
  disabled: { type: Boolean, default: false },
  agentUnavailable: { type: Boolean, default: false },
  attachments: { type: Array, default: () => [] },
  // Telemetry surface for voice input: main_chat | flow_chat
  voiceSurface: { type: String, default: 'main_chat' },
  // The chat's project. Uploaded attachments become assets in it. When the
  // host doesn't pass one, the active working project is used.
  projectId: { type: Number, default: undefined },
  // The one optional context line (where the message lands). Quiet, on the
  // composer's own left edge; a host never builds its own.
  context: { type: String, default: '' }
})

const emit = defineEmits([
  'update:modelValue',
  'submit',
  'keydown',
  'attach-workspace-file',
  'update:attachments'
])

const textareaRef = ref(null)
// Keep the exposed scrolling element available to existing hosts.
const scrollWrapRef = textareaRef
const uploadInputRef = ref(null)
const dragging = ref(false)
const voiceBtn = ref(null)
const inputText = computed(() => props.draft ? props.draft.text : props.modelValue)
const uploadProjectId = useOwnerProject(() => props.projectId)
let resizeFrame = null

// Space-to-dictate (when empty) + propagate keydown for history nav etc.
function onTextareaKeydown(event) {
  voiceBtn.value?.handleInputKeydown(event)
  emit('keydown', event)
}

function onTextareaKeyup(event) {
  voiceBtn.value?.handleInputKeyup(event)
}

// Focus ring: shown on real focus only. `focusQuietly()` is for focus a page
// gives the field on load; no ring until the person interacts.
const hasFocus = ref(false)
const quiet = ref(false)
const ringVisible = computed(() => hasFocus.value && !quiet.value)
function onShellFocusOut(event) {
  if (event.currentTarget.contains(event.relatedTarget)) return
  hasFocus.value = false
  quiet.value = false
}
function focusQuietly() {
  quiet.value = true
  textareaRef.value?.focus()
}

// Expose refs so parent can access textarea
defineExpose({
  textareaRef,
  scrollWrapRef,
  focus: () => textareaRef.value?.focus(),
  focusQuietly,
  autoResize,
  addAttachmentFromMediaId
})

// ==================== Voice input ====================

function getText() {
  return inputText.value || ''
}

function setText(text) {
  if (props.draft) props.draft.text = text
  else emit('update:modelValue', text)
  autoResize()
}

function focusTextarea() {
  textareaRef.value?.focus()
}

function autoResize() {
  if (resizeFrame !== null) return
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    resizeTextarea()
  })
}

function resizeTextarea() {
  const el = textareaRef.value
  if (!el) return
  // Measuring at auto height temporarily collapses the field and can reset its
  // scroll offset. Preserve the browser's caret scroll (or the user's scroll).
  const scrollTop = el.scrollTop
  el.style.height = 'auto'
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight || '24')
  const minHeight = el.rows * lineHeight
  el.style.height = Math.min(10 * lineHeight, Math.max(minHeight, el.scrollHeight)) + 'px'
  el.scrollTop = scrollTop
}

// ==================== Attachments ====================

function updateAttachments(newAttachments) {
  emit('update:attachments', newAttachments)
}

function removeAttachment(index) {
  const updated = [...props.attachments]
  updated.splice(index, 1)
  updateAttachments(updated)
}

function addAttachmentFromMediaId(mediaId) {
  if (props.agentUnavailable) return
  if (props.attachments.some(a => a.media_id === mediaId)) return
  updateAttachments([...props.attachments, { media_id: mediaId }])
}

function openUploadPicker() {
  if (props.agentUnavailable) return
  uploadInputRef.value?.click()
}

async function handleUploadSelect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  event.target.value = ''
  await uploadFileToAttachments(file)
}

async function uploadFileToAttachments(file) {
  if (!file.type.startsWith('image/')) {
    addToast('Only images can be attached.', 'error')
    return
  }
  const draft = props.draft
  try {
    const formData = new FormData()
    formData.append('file', file)
    appendProjectId(formData, uploadProjectId.value)
    const response = await axios.post('/api/generate/upload-reference', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    const attachment = {
      media_id: response.data.media_id,
      path: response.data.path,
      filename: response.data.filename
    }
    // An upload may finish after navigation. Attach to its original draft.
    if (draft) draft.attachments.push(attachment)
    else updateAttachments([...props.attachments, attachment])
  } catch (error) {
    reportActionError("Couldn't upload file.", error)
  }
}

// ==================== Drag-drop ====================

function onDragOver() {
  if (props.agentUnavailable) return
  dragging.value = true
}

function resetDragging() {
  dragging.value = false
}

function onDragLeave(event) {
  // Ignore transitions between descendants of the input. Without this check,
  // moving over attachments and controls can briefly dismiss the overlay.
  const nextTarget = event.relatedTarget
  if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return
  resetDragging()
}

async function onDrop(event) {
  resetDragging()
  if (props.agentUnavailable) return

  const workspaceFile = event.dataTransfer?.getData('application/x-stimma-workspace-file')
  if (workspaceFile) {
    try { emit('attach-workspace-file', JSON.parse(workspaceFile)) } catch { /* Ignore malformed external drags. */ }
    nextTick(() => textareaRef.value?.focus())
    return
  }

  // A drag of several picked images from a chat collection.
  try {
    const items = JSON.parse(event.dataTransfer?.getData('application/x-stimma-assets') || '{}').items || []
    if (items.length > 1 && items.every(item => item.media_id)) {
      updateAttachments([...props.attachments, ...items.filter(item => !props.attachments.some(a => a.media_id === item.media_id)).map(item => ({ media_id: item.media_id }))])
      nextTick(() => textareaRef.value?.focus())
      return
    }
  } catch { /* Ignore malformed external drags. */ }

  // Check for media_id from in-app drag
  const mediaId = event.dataTransfer?.getData('application/x-media-id')
  if (mediaId) {
    addAttachmentFromMediaId(parseInt(mediaId))
    nextTick(() => textareaRef.value?.focus())
    return
  }

  // Check for files (external drag)
  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    const imageFile = Array.from(files).find(f => f.type.startsWith('image/'))
    if (imageFile) {
      await uploadFileToAttachments(imageFile)
      nextTick(() => textareaRef.value?.focus())
    }
  }
}

onMounted(() => {
  autoResize()
  // A drag can start inside this composer and be dropped elsewhere. In that
  // case the composer receives neither drop nor a reliable dragleave, while
  // dragend still reaches the window.
  window.addEventListener('dragend', resetDragging, true)
  window.addEventListener('drop', resetDragging, true)
})

onUnmounted(() => {
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  window.removeEventListener('dragend', resetDragging, true)
  window.removeEventListener('drop', resetDragging, true)
})

watch(() => props.agentUnavailable, unavailable => {
  if (unavailable) resetDragging()
})

// Includes programmatic changes (history navigation, send/restore, dictation).
watch(inputText, autoResize, { flush: 'post' })
</script>
