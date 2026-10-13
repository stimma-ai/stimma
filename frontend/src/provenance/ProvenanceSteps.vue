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
        class="absolute -left-[16.5px] top-[9.5px] w-[9px] h-[9px] rounded-full bg-surface border-2 border-solid border-content-tertiary"
      ></span>
      <!-- Header: what made it (task glyph + tool), when; step actions on the right -->
      <div class="flex items-center gap-1.5 min-w-0 min-h-7">
        <StepIcon v-if="step.icon" :icon="step.icon" class="w-3.5 h-3.5 flex-shrink-0 text-content-tertiary" />
        <span class="text-[13px] font-semibold text-content truncate">{{ step.tool }}</span>
        <Tip v-if="step.date" :text="formatDateTime(step.date)">
          <span class="ml-0.5 font-mono tabular-nums text-[10px] text-content-muted flex-shrink-0">
            {{ (step.imported ? 'imported ' : '') + formatRelativeTime(step.date) }}
          </span>
        </Tip>
        <div class="flex-1"></div>
        <slot name="actions" :step="step" :index="idx" />
      </div>

      <div class="mt-1.5 space-y-2.5">
        <ProvenanceInputs :inputs="step.inputs" :size="inputSize" />

        <!-- What the editor did, when this step came out of the editor -->
        <EditSteps :steps="step.editSteps" />

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
        <KeyValueList :rows="step.facts" />

        <button
          v-if="step.rawMetadata && host.openRawMetadata"
          type="button"
          class="flex w-full items-center justify-between bg-transparent border-none p-0 text-xs text-content-tertiary cursor-pointer hover:text-content transition-colors duration-150"
          @click="host.openRawMetadata(step.rawMetadata)"
        >
          <span>External metadata</span>
          <ChevronRightIcon class="w-3 h-3" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRightIcon } from '@heroicons/vue/24/outline'
import EditSteps from './EditSteps.vue'
import PromptBlock from './PromptBlock.vue'
import ProvenanceInputs from './ProvenanceInputs.vue'
import StepIcon from './StepIcon.vue'
import Tip from './Tip.vue'
import KeyValueList from '../components/ui/KeyValueList.vue'
import { formatRelativeTime } from '../utils/timeFormat.js'
import { formatDateTime } from './format.ts'
import { useProvenanceHost } from './host.ts'
import type { ViewStep } from './types.ts'

const props = withDefaults(defineProps<{
  steps: ViewStep[]
  /** Label the prompt (cards without a step header need it). */
  promptLabels?: boolean
  inputSize?: 'sm' | 'md'
}>(), {
  promptLabels: false,
  inputSize: 'md',
})

const host = useProvenanceHost()
const railed = computed(() => props.steps.length > 1)
</script>
