<template>
  <div class="segment-editor rounded-md border border-edge overflow-hidden focus-within:border-accent transition-colors">
    <div ref="editorMount"></div>

    <!-- Bottom Action Bar -->
    <div class="px-3 py-1.5 flex items-center justify-end bg-surface border-t border-edge">
      <div class="flex items-center gap-1.5">
        <!-- Vim/Reg toggle -->
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

        <!-- Mono/Sans toggle -->
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

        <!-- Help button -->
        <button
          ref="helpBtnRef"
          @click="toggleHelp"
          :class="[
            'text-[10px] font-medium px-1.5 py-0.5 rounded transition-colors',
            showHelp ? 'text-content-secondary bg-surface-raised' : 'text-content-muted hover:text-content-secondary'
          ]"
          title="Prompt syntax help"
        >
          HELP
        </button>
      </div>
    </div>
  </div>

  <!-- Help popover teleported to body to avoid clipping -->
  <Teleport to="body">
    <div
      v-if="showHelp"
      class="fixed inset-0 z-menu"
      @click="showHelp = false"
    >
      <div
        class="absolute p-4 bg-surface border border-edge rounded-lg shadow-xl w-80"
        :style="helpPopoverStyle"
        @click.stop
      >
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-1.5">
            <svg class="w-3 h-3 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" /></svg>
            <span class="text-xs font-medium text-content-secondary">Prompt Syntax</span>
          </div>
          <button @click="showHelp = false" class="text-content-muted hover:text-content-secondary p-0.5">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Wildcards -->
        <div class="mb-3">
          <div class="flex items-center gap-2 mb-1">
            <code class="text-green-600 bg-green-500/10 px-1.5 py-0.5 rounded text-xs">{red|blue|green}</code>
          </div>
          <p class="text-xs text-content-tertiary leading-relaxed">
            Picks one option randomly each time you generate. Great for improving variety.
          </p>
        </div>

        <!-- Named Wildcards -->
        <div class="mb-3">
          <div class="flex items-center gap-2 mb-1">
            <code class="text-amber-600 bg-amber-500/10 px-1.5 py-0.5 rounded text-xs" v-text="'{{name}}'"></code>
          </div>
          <p class="text-xs text-content-tertiary leading-relaxed">
            Expands to a random value from a wildcard list, or the fixed content of a segment.
          </p>
        </div>

        <!-- Comments -->
        <div class="mb-3">
          <div class="flex items-center gap-2 mb-1">
            <code class="text-gray-500 italic bg-zinc-500/10 px-1.5 py-0.5 rounded text-xs"># comment</code>
          </div>
          <p class="text-xs text-content-tertiary leading-relaxed">
            Guide the AI improvement model. Stripped before generation.
          </p>
        </div>

        <!-- Verbatim -->
        <div>
          <div class="flex items-center gap-2 mb-1">
            <code class="text-blue-500 bg-blue-500/10 px-1.5 py-0.5 rounded text-xs">[verbatim text]</code>
          </div>
          <p class="text-xs text-content-tertiary leading-relaxed">
            Preserved as-is, invisible to the improvement model.
          </p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useCodeMirrorPrompt } from '../../../composables/useCodeMirrorPrompt'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const editorMount = ref<HTMLElement | null>(null)
const showHelp = ref(false)
const helpBtnRef = ref<HTMLElement | null>(null)
const helpPopoverStyle = ref<Record<string, string>>({})

const { vimEnabled, monospaceEnabled, toggleVim, toggleMonospace } = useCodeMirrorPrompt({
  mountRef: editorMount,
  modelValue: () => props.modelValue,
  placeholder: 'Enter segment content...',
  onChange: (value: string) => {
    emit('update:modelValue', value)
  },
  onBlur: () => {},
})

function toggleHelp() {
  if (showHelp.value) {
    showHelp.value = false
    return
  }
  // Position relative to the HELP button
  if (helpBtnRef.value) {
    const rect = helpBtnRef.value.getBoundingClientRect()
    helpPopoverStyle.value = {
      bottom: `${window.innerHeight - rect.top + 8}px`,
      right: `${window.innerWidth - rect.right}px`,
    }
  }
  showHelp.value = true
}
</script>

<style scoped>
.segment-editor :deep(.cm-editor) {
  min-height: 60px !important;
  max-height: 200px !important;
  border-radius: 0 !important;
}
</style>
