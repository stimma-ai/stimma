<template>
  <!-- Timeline rail (§3.1 grammar): steps separate by the rail and its dots
       when history stacks; a single step renders flat — a lone dot on a rail
       would be structure separating nothing. -->
  <div :class="railed ? 'relative pl-4' : ''">
    <div v-if="railed" class="absolute left-[3px] top-2 bottom-2 w-[2px] rounded-full bg-edge-subtle"></div>
    <div
      v-for="(step, idx) in steps"
      :key="step.key"
      class="relative"
      :class="idx > 0 ? 'mt-5' : ''"
      data-testid="provenance-step"
    >
      <span
        v-if="railed"
        class="absolute -left-[16.5px] top-[9.5px] w-[9px] h-[9px] rounded-full bg-surface border-2 border-content-tertiary"
      ></span>
      <!-- Header: what made it, when; step actions on the right -->
      <div class="flex items-center gap-2 min-w-0 min-h-7">
        <span class="text-[13px] font-semibold text-content truncate">{{ step.tool }}</span>
        <Tooltip v-if="step.date" :text="formatDateTime(step.date)">
          <span class="font-mono tabular-nums text-[10px] text-content-muted flex-shrink-0">
            {{ (step.imported ? 'imported ' : '') + formatRelativeTime(step.date) }}
          </span>
        </Tooltip>
        <div class="flex-1"></div>
        <slot name="actions" :step="step" :index="idx" />
      </div>

      <div class="mt-1.5 space-y-2.5">
        <ProvenanceInputs
          :inputs="step.inputs"
          :allow-compare="allowCompare"
          :size="inputSize"
          @navigate="$emit('navigate', $event)"
          @compare="$emit('compare', $event)"
        />

        <!-- What the editor did, when this step came out of the editor -->
        <EditStackSummary :stack="step.editStack" />

        <PromptBlock :text="step.prompt" :label="promptLabels ? 'Prompt' : ''" />
        <PromptBlock
          v-if="step.originalPrompt"
          :text="step.originalPrompt"
          label="Original prompt"
          muted
        />
        <PromptBlock :text="step.negativePrompt" label="Negative prompt" />

        <!-- Params, chain and LoRAs: ONE KeyValueList so the hairline between
             groups exists (adjacent lists drop the rule at the seam). -->
        <KeyValueList :rows="stepFactRows(step)" />

        <button
          v-if="step.rawMetadata"
          type="button"
          class="flex w-full items-center justify-between bg-transparent border-none p-0 text-xs text-content-tertiary cursor-pointer hover:text-content transition-colors duration-150"
          @click="rawMetadata = step.rawMetadata"
        >
          <span>External metadata</span>
          <ChevronRightIcon class="w-3 h-3" />
        </button>
      </div>
    </div>

    <Modal
      :show="!!rawMetadata"
      size="custom"
      custom-class="w-full max-w-[80vw] h-[80vh] compact:h-[85dvh] flex flex-col overflow-hidden"
      @close="rawMetadata = null"
    >
      <template #header>
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-content m-0">External metadata</h3>
          <Tooltip text="Close">
            <IconButton aria-label="Close" @click="rawMetadata = null">
              <XMarkIcon class="w-5 h-5" />
            </IconButton>
          </Tooltip>
        </div>
      </template>
      <div class="flex-1 min-h-0">
        <ReadOnlyCode v-if="rawMetadata" :text="rawMetadataDisplay.text" :name="rawMetadataDisplay.name" />
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronRightIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import EditStackSummary from './EditStackSummary.vue'
import PromptBlock from './PromptBlock.vue'
import ProvenanceInputs from './ProvenanceInputs.vue'
import KeyValueList from '../ui/KeyValueList.vue'
import IconButton from '../ui/IconButton.vue'
import Modal from '../ui/Modal.vue'
import Tooltip from '../ui/Tooltip.vue'
import ReadOnlyCode from '../viewers/ReadOnlyCode.vue'
import { formatRelativeTime } from '../../utils/timeFormat'
import { formatDateTime, stepFactRows, type ProvenanceStep } from '../../utils/mediaProvenance'

const props = withDefaults(defineProps<{
  steps: ProvenanceStep[]
  /** Offer "Compare" on library inputs. */
  allowCompare?: boolean
  /** Label the prompt (cards without a step header need it). */
  promptLabels?: boolean
  inputSize?: 'sm' | 'md'
}>(), {
  allowCompare: false,
  promptLabels: false,
  inputSize: 'md',
})

defineEmits<{
  (e: 'navigate', mediaId: number): void
  (e: 'compare', mediaId: number): void
}>()

const railed = computed(() => props.steps.length > 1)

const rawMetadata = ref<string | null>(null)
const rawMetadataDisplay = computed(() => {
  const raw = rawMetadata.value || ''
  try {
    return { text: JSON.stringify(JSON.parse(raw), null, 2), name: 'metadata.json' }
  } catch {
    return { text: raw, name: 'metadata.txt' }
  }
})
</script>
