<template>
  <div class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal p-8" @click.self="close" @keydown.esc.stop="onEscape">
    <div class="bg-surface border border-edge rounded-lg w-full max-w-[900px] max-h-[85vh] flex flex-col shadow-[0_20px_25px_-5px_rgba(0,0,0,0.5)]">
      <div class="flex justify-between items-center px-6 py-4 border-b border-edge">
        <h2 class="m-0 text-lg font-semibold text-content">{{ stimpack ? `Edit: ${stimpack.display_name || stimpack.name}` : 'New Stimpack' }}</h2>
        <button
          class="bg-transparent border-none text-content-tertiary cursor-pointer p-2 flex items-center justify-center rounded transition-all hover:bg-overlay-light hover:text-content"
          @click="close"
        >
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="flex-1 p-6 overflow-y-auto flex flex-col gap-4">
        <!-- Display Name field -->
        <div class="space-y-1">
          <label class="block text-sm font-medium text-content-secondary">Display Name</label>
          <input
            v-model="form.display_name"
            type="text"
            placeholder="My Stimpack Name"
            class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            @input="autoGenerateSlug"
          />
        </div>

        <!-- Slug (name) field -->
        <div class="space-y-1">
          <label class="block text-sm font-medium text-content-secondary">Slug</label>
          <input
            v-model="form.name"
            type="text"
            :disabled="!!stimpack"
            placeholder="my-stimpack-name"
            class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-accent disabled:opacity-50 disabled:cursor-not-allowed font-mono text-xs"
          />
          <p v-if="!stimpack" class="text-xs text-content-muted">Auto-generated from display name. Used as the stimpack identifier.</p>
        </div>

        <!-- Description field -->
        <div class="space-y-1">
          <label class="block text-sm font-medium text-content-secondary">Description</label>
          <input
            v-model="form.description"
            type="text"
            placeholder="What does this stimpack do?"
            class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
          />
        </div>

        <!-- Tags field -->
        <div class="space-y-1">
          <label class="block text-sm font-medium text-content-secondary">Tags</label>
          <input
            v-model="tagsInput"
            type="text"
            placeholder="tag1, tag2, tag3"
            class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
          />
          <p class="text-xs text-content-muted">Comma-separated list of tags.</p>
        </div>

        <!-- Content field -->
        <div class="space-y-1 flex-1 flex flex-col">
          <label class="block text-sm font-medium text-content-secondary">Content</label>
          <div class="stimpack-editor rounded-md border border-edge overflow-hidden focus-within:border-accent transition-colors">
            <div ref="editorMount"></div>
            <div class="px-3 py-1.5 flex items-center justify-end bg-surface border-t border-edge">
              <div class="flex items-center gap-1.5">
                <button
                  @click="toggleVim"
                  :class="[
                    'text-[10px] font-mono font-medium px-1.5 py-0.5 rounded transition-colors',
                    vimEnabled
                      ? 'text-green-500 bg-green-500/10'
                      : 'text-content-muted hover:text-content-secondary'
                  ]"
                  :title="vimEnabled ? 'Switch to regular keybindings' : 'Switch to Vim keybindings'"
                >
                  {{ vimEnabled ? 'VIM' : 'STD' }}
                </button>
                <button
                  @click="toggleMonospace"
                  :class="[
                    'text-[10px] font-medium px-1.5 py-0.5 rounded transition-colors',
                    monospaceEnabled
                      ? 'text-accent bg-accent/10 font-mono'
                      : 'text-content-muted hover:text-content-secondary'
                  ]"
                  :title="monospaceEnabled ? 'Switch to proportional font' : 'Switch to monospace font'"
                >
                  {{ monospaceEnabled ? 'MONO' : 'SANS' }}
                </button>
              </div>
            </div>
          </div>
          <p class="text-xs text-content-muted">Tip: You can also ask the agent to edit this stimpack for you in chat.</p>
        </div>
      </div>

      <div class="px-6 py-4 border-t border-edge flex justify-end gap-3">
        <button
          class="bg-surface-raised text-content border-none py-2.5 px-6 rounded-lg text-sm font-medium cursor-pointer transition-all hover:bg-surface-hover"
          @click="close"
        >
          Cancel
        </button>
        <button
          class="bg-accent text-white border-none py-2.5 px-6 rounded-md text-sm font-medium cursor-pointer transition-all hover:bg-accent/90"
          @click="save"
        >
          Save
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useCodeMirrorPrompt } from '../../composables/useCodeMirrorPrompt'
import type { StimpackDetail } from '../../composables/useStimpacksApi'

const props = defineProps<{
  stimpack?: StimpackDetail | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', data: { name: string; display_name: string; description: string; tags: string[]; content: string }): void
}>()

const form = ref({
  name: props.stimpack?.name || '',
  display_name: props.stimpack?.display_name || '',
  description: props.stimpack?.description || '',
  content: props.stimpack?.content || '',
})

function autoGenerateSlug() {
  // Only auto-generate slug for new stimpacks (not when editing)
  if (props.stimpack) return
  form.value.name = form.value.display_name
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[\s]+/g, '-')
}

const tagsInput = ref(props.stimpack?.tags?.join(', ') || '')
const editorMount = ref<HTMLElement | null>(null)

const { vimEnabled, monospaceEnabled, toggleVim, toggleMonospace } = useCodeMirrorPrompt({
  mountRef: editorMount,
  modelValue: () => form.value.content,
  placeholder: 'Stimpack instructions in markdown...',
  onChange: (value: string) => {
    form.value.content = value
  },
  onBlur: () => {},
})

function onEscape() {
  // Don't close modal if the editor is focused (Escape is used by vim mode)
  if (editorMount.value?.contains(document.activeElement)) return
  close()
}

function close() {
  emit('close')
}

function save() {
  const tags = tagsInput.value
    .split(',')
    .map(t => t.trim())
    .filter(t => t.length > 0)

  emit('save', {
    name: form.value.name,
    display_name: form.value.display_name,
    description: form.value.description,
    tags,
    content: form.value.content,
  })
}
</script>

<style scoped>
.stimpack-editor :deep(.cm-editor) {
  min-height: 280px !important;
  max-height: 500px !important;
}
</style>
