<template>
  <Modal
    :show="true"
    size="custom"
    custom-class="max-w-[900px] w-full max-h-[85vh] flex flex-col overflow-hidden"
    :close-on-esc="false"
    @close="close"
  >
    <template #header>
      <div class="flex justify-between items-center">
        <h2 class="m-0 text-lg font-semibold text-content">{{ stimpack ? `Edit: ${stimpack.display_name || stimpack.name}` : 'New Stimpack' }}</h2>
        <IconButton aria-label="Close" title="Close" @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

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

    <template #footer>
      <Button variant="secondary" @click="close">Cancel</Button>
      <Button variant="primary" @click="save">Save</Button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useCodeMirrorPrompt } from '../../composables/useCodeMirrorPrompt'
import type { StimpackDetail } from '../../composables/useStimpacksApi'
import Modal from '../ui/Modal.vue'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'

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

// Modal.vue's Esc handling is disabled (close-on-esc="false") because Escape
// must NOT close this modal while the CodeMirror vim mode has focus (vim
// uses Escape itself). This replicates the prior behavior exactly.
function onWindowKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (editorMount.value?.contains(document.activeElement)) return
  close()
}

onMounted(() => {
  window.addEventListener('keydown', onWindowKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydown)
})

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
