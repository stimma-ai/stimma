<template>
  <div v-if="steps.length">
    <!-- One line per step, in the Edits list's order. The full stack — every
         candidate, mask and slider — stays in the editor. -->
    <div class="divide-y divide-edge-subtle">
      <div v-for="step in visibleSteps" :key="step.key" class="py-1.5" data-testid="provenance-edit-step">
        <div class="flex justify-between gap-3" :class="step.thumb ? 'items-center' : 'items-baseline'">
          <span class="min-w-0 flex-1 text-xs text-content truncate" :title="step.name">
            {{ step.name }}
          </span>
          <span
            v-if="step.detail"
            class="min-w-0 max-w-[60%] text-xs text-content-tertiary text-right truncate"
            :title="step.detail"
          >
            {{ step.detail }}
          </span>
          <!-- The reference image the edit was given -->
          <span v-if="step.thumb" class="w-5 h-5 flex-shrink-0 rounded-media overflow-hidden bg-matte">
            <component :is="host.thumbnail" :thumb-ref="step.thumb" :fallback-ref="null" :alt="step.name" :size="20" />
          </span>
        </div>
        <p
          v-if="step.note"
          class="m-0 mt-0.5 text-xs leading-relaxed text-content-tertiary line-clamp-2"
          :title="step.note"
        >
          {{ step.note }}
        </p>
      </div>
      <!-- Last child inside the rules, so nothing trails the list. -->
      <button
        v-if="hiddenCount"
        type="button"
        class="w-full py-1.5 bg-transparent border-none text-left text-xs text-content-tertiary cursor-pointer hover:text-content-secondary transition-colors duration-150"
        @click="expanded = true"
      >
        Show {{ hiddenCount }} more
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * What an editor save did, in one line per step. An image that came out of
 * the editor has no model and no prompt to show; this is the account of the
 * work: which repairs, which adjustments, whether a model made new pixels.
 */
import { computed, ref } from 'vue'
import { useProvenanceHost } from './host.ts'
import type { ViewEditStep } from './types.ts'

/** Steps beyond this fold behind a disclosure; deep stacks are common. */
const COLLAPSE_AFTER = 6

const props = defineProps<{ steps: ViewEditStep[] }>()

const host = useProvenanceHost()
const expanded = ref(false)

const visibleSteps = computed(() =>
  expanded.value ? props.steps : props.steps.slice(0, COLLAPSE_AFTER),
)
const hiddenCount = computed(() => props.steps.length - visibleSteps.value.length)
</script>
