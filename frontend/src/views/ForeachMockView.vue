<template>
  <div class="w-full h-full overflow-auto bg-base">
    <div class="max-w-[1280px] mx-auto p-6 space-y-6">
      <div class="flex items-center gap-3">
        <h1 class="text-[16px] font-medium text-content">Foreach grouping mock</h1>
        <span class="text-[11px] text-content-muted italic">
          Workflow-view prototype · not wired to runtime
        </span>
        <div class="flex-1" />
        <div class="flex items-center gap-1 text-[12px]">
          <button
            v-for="s in scenarios"
            :key="s.id"
            type="button"
            class="px-2.5 py-1 rounded-md border transition-colors"
            :class="s.id === activeScenarioId
              ? 'bg-accent border-transparent text-white'
              : 'border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-subtle'"
            @click="activeScenarioId = s.id"
          >{{ s.label }}</button>
        </div>
      </div>

      <div class="text-[12px] text-content-muted leading-relaxed space-y-1.5">
        <p>
          The dashed container is what a <code>foreach</code> collapses into inside the workflow graph.
          Body nodes show the canonical shape (union across iterations); optional nodes are marked.
          Status ribbons inside each body node mirror the block chart 1:1 (same iteration order) so
          failure propagation is visible vertically.
        </p>
        <p>
          Click a block to focus an iteration; nodes swap to that iteration's tile. Use <kbd
            class="px-1 rounded border border-edge-subtle text-[10px]"
          >←</kbd> / <kbd class="px-1 rounded border border-edge-subtle text-[10px]">→</kbd>
          to step through the active filter. <kbd
            class="px-1 rounded border border-edge-subtle text-[10px]"
          >Esc</kbd> returns to aggregate.
        </p>
      </div>

      <ForeachGroupNode :key="activeScenarioId" :group="activeGroup" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ForeachGroupNode from '../components/flow/mock/ForeachGroupNode.vue'
import {
  buildScenario4,
  buildScenario40,
  buildScenario400,
} from '../components/flow/mock/foreachMockData'

const scenarios = [
  { id: 'small-4',  label: '4 iterations' },
  { id: 'mid-40',   label: '40 iterations' },
  { id: 'big-400',  label: '400 iterations' },
] as const

type ScenarioId = (typeof scenarios)[number]['id']
const activeScenarioId = ref<ScenarioId>('mid-40')

const activeGroup = computed(() => {
  switch (activeScenarioId.value) {
    case 'small-4': return buildScenario4()
    case 'big-400': return buildScenario400()
    case 'mid-40':
    default:        return buildScenario40()
  }
})
</script>
