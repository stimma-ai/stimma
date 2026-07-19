<template>
  <!-- Chain step = the LoRA row grammar: enable dot · name · inline subtitle ·
       hover controls · hairline. Row click expands; dot click toggles. -->
  <div
    :class="[
      'group relative transition-colors',
      dragging ? 'opacity-30' : '',
    ]"
    draggable="true"
    @dragstart="$emit('grip-dragstart', $event)"
    @dragend="$emit('grip-dragend')"
  >
    <div class="flex items-center gap-1.5 py-1.5">
      <!-- Enable dot (click toggles; amber = needs attention) -->
      <button
        type="button"
        class="shrink-0 w-3 flex items-center justify-center"
        :title="step.enabled ? 'Disable step' : 'Enable step'"
        @click.stop="$emit('set-enabled', !step.enabled)"
      >
        <span v-if="incompatible || unavailable" class="w-2.5 h-2.5 rounded-full bg-amber-400" />
        <span v-else-if="step.enabled" class="w-2.5 h-2.5 rounded-full bg-accent-hi" />
        <span v-else class="w-2.5 h-2.5 rounded-full border border-content-muted" />
      </button>

      <!-- Name + inline subtitle; click expands settings -->
      <button
        type="button"
        :class="['flex-1 min-w-0 text-left flex items-baseline gap-1.5', step.enabled ? '' : 'opacity-50']"
        @click="$emit('toggle-expanded')"
      >
        <span class="text-[13px] text-content truncate" :class="step.enabled ? 'font-medium' : ''">{{ title }}</span>
        <span v-if="unavailable" class="shrink-0 text-[10px] font-medium text-amber-500">unavailable</span>
        <span class="min-w-0 truncate text-[11px] text-content-muted">
          <template v-if="incompatible"><span class="text-amber-500">Needs {{ neededInput }} input — skipped</span></template>
          <template v-else-if="step.kind === 'tool' && provider">
            <span :class="provider.isStimmaCloud ? 'stimma-cloud-text font-medium' : ''">{{ provider.name }}</span>
          </template>
          <template v-else-if="step.kind === 'filter'">{{ summary }}</template>
        </span>
      </button>

      <!-- Output thumbnail (when the step has run) -->
      <MediaImage
        v-if="thumbMediaId"
        :media-id="thumbMediaId"
        :thumbnail="true"
        :size="128"
        class="w-6 h-6 rounded-media object-cover shrink-0"
      />

      <!-- Hover controls: remove + drag grip (right, like LoRA rows) -->
      <div class="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          type="button"
          class="w-4 h-4 flex items-center justify-center text-content-muted hover:!text-red-500"
          title="Remove step"
          @click.stop="$emit('remove')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
        
      </div>
    </div>

    <!-- Expanded settings: the wash-inset disclosure -->
    <div v-if="expanded" class="bg-overlay-faint rounded-md mb-2 px-3 py-2">
      <slot name="settings"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MediaImage from '../../media/MediaImage.vue'
import type { ChainStep } from '../../../utils/postProcessingChain'

const props = defineProps<{
  step: ChainStep
  title: string
  summary: string
  expanded: boolean
  /** Standard provider treatment for the sub row (tool steps). */
  provider?: { name: string; isStimmaCloud: boolean } | null
  incompatible?: boolean
  neededInput?: string
  unavailable?: boolean
  dragging?: boolean
  thumbMediaId?: number | null
}>()

const emit = defineEmits<{
  (e: 'toggle-expanded'): void
  (e: 'set-enabled', enabled: boolean): void
  (e: 'remove'): void
  (e: 'grip-dragstart', ev: DragEvent): void
  (e: 'grip-dragend'): void
}>()



</script>
