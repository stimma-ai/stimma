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
        v-if="dragging"
        class="absolute inset-0 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-sm z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-blue-500"
      >
        <div class="flex flex-col items-center gap-2 text-blue-500">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-10 h-10">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
          </svg>
          <span class="text-sm font-medium">Drop Asset Here</span>
        </div>
      </div>
    </Transition>

    <!-- Rounded input container -->
    <div class="bg-surface border border-edge rounded-2xl pt-1 overflow-hidden">
      <!-- Optional header above attachments — used by FlowView to render
           the context-reference tray. Always rendered; tray decides its own
           empty-state treatment so the layout doesn't jump when refs are
           added/removed. -->
      <slot name="context-header" />

      <!-- Attachments preview -->
      <ChatInputAttachments
        v-if="attachments.length > 0"
        :attachments="attachments"
        @remove="removeAttachment"
      />

      <!-- Textarea scroll wrapper -->
      <div ref="scrollWrapRef" class="chat-input-scroll-wrap overflow-y-auto mx-3 mt-2">
        <textarea v-no-autocorrect
          ref="textareaRef"
          :value="modelValue"
          @input="$emit('update:modelValue', $event.target.value); autoResize()"
          :placeholder="placeholder"
          :rows="rows"
          class="chat-input-textarea w-full bg-transparent text-content pl-1 pr-1 pb-2 focus:outline-none resize-none block"
          @keydown.enter.exact.prevent="$emit('submit')"
          @keydown="onTextareaKeydown"
          @keyup="onTextareaKeyup"
        />
      </div>

      <!-- Action bar -->
      <div class="flex items-center justify-between px-3 pb-2">
        <!-- Left: model picker + upload button -->
        <div class="flex items-center gap-1">
          <slot name="model-picker" />
          <button
            @click="openUploadPicker"
            class="w-8 h-8 flex items-center justify-center rounded-full text-content-muted hover:text-content-secondary hover:bg-white/[0.05] transition-colors"
            title="Add image"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </button>
          <VoiceInputButton ref="voiceBtn" :get-text="getText" :set-text="setText" :focus="focusTextarea" :surface="voiceSurface" />
        </div>

        <!-- Right: slot for custom buttons, or default send -->
        <slot name="actions">
          <button
            @click="$emit('submit')"
            :disabled="(!modelValue?.trim() && attachments.length === 0) || disabled"
            class="w-8 h-8 flex items-center justify-center rounded-full bg-content text-surface transition-colors disabled:opacity-30"
            title="Send"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4">
              <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z" transform="rotate(-90 12 12)" />
            </svg>
          </button>
        </slot>
      </div>
    </div>

    <!-- Hidden file input -->
    <input
      ref="uploadInputRef"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="handleUploadSelect"
    />
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import axios from 'axios'
import ChatInputAttachments from './ChatInputAttachments.vue'
import VoiceInputButton from '../voice/VoiceInputButton.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'Type a message...' },
  rows: { type: Number, default: 2 },
  disabled: { type: Boolean, default: false },
  attachments: { type: Array, default: () => [] },
  // Telemetry surface for voice input: main_chat | flow_chat
  voiceSurface: { type: String, default: 'main_chat' }
})

const emit = defineEmits([
  'update:modelValue',
  'submit',
  'keydown',
  'update:attachments'
])

const textareaRef = ref(null)
const scrollWrapRef = ref(null)
const uploadInputRef = ref(null)
const dragging = ref(false)
const voiceBtn = ref(null)

// Space-to-dictate (when empty) + propagate keydown for history nav etc.
function onTextareaKeydown(event) {
  voiceBtn.value?.handleInputKeydown(event)
  emit('keydown', event)
}

function onTextareaKeyup(event) {
  voiceBtn.value?.handleInputKeyup(event)
}

// Expose refs so parent can access textarea
defineExpose({
  textareaRef,
  scrollWrapRef,
  focus: () => textareaRef.value?.focus(),
  autoResize,
  addAttachmentFromMediaId
})

// ==================== Voice input ====================

function getText() {
  return props.modelValue || ''
}

function setText(text) {
  emit('update:modelValue', text)
  nextTick(autoResize)
}

function focusTextarea() {
  textareaRef.value?.focus()
}

function autoResize() {
  const el = textareaRef.value
  const wrap = scrollWrapRef.value
  if (!el) return
  el.style.height = 'auto'
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight || '24')
  const minHeight = el.rows * lineHeight
  el.style.height = Math.max(minHeight, el.scrollHeight) + 'px'
  if (wrap) {
    wrap.style.maxHeight = Math.round(10 * lineHeight) + 'px'
  }
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
  if (props.attachments.some(a => a.media_id === mediaId)) return
  updateAttachments([...props.attachments, { media_id: mediaId }])
}

function openUploadPicker() {
  uploadInputRef.value?.click()
}

async function handleUploadSelect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  event.target.value = ''
  await uploadFileToAttachments(file)
}

async function uploadFileToAttachments(file) {
  if (!file.type.startsWith('image/')) return
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await axios.post('/api/generate/upload-reference', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    updateAttachments([...props.attachments, {
      media_id: response.data.media_id,
      path: response.data.path,
      filename: response.data.filename
    }])
  } catch (error) {
    console.error('Failed to upload file:', error)
  }
}

// ==================== Drag-drop ====================

function onDragOver() {
  dragging.value = true
}

function onDragLeave() {
  dragging.value = false
}

async function onDrop(event) {
  dragging.value = false

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
</script>
