<template>
  <div class="plan-approval">
    <!-- Header and visualization - only show if showPlan is true (otherwise plan is shown separately) -->
    <template v-if="showPlan">
      <div class="flex items-center gap-2 mb-4">
        <div class="p-1.5 rounded-lg bg-blue-500/20">
          <ClipboardDocumentListIcon class="w-4 h-4 text-blue-500" />
        </div>
        <div class="text-sm font-medium text-content">Plan</div>
        <div v-if="nodeCount > 0" class="text-xs text-content-muted">
          {{ nodeCount }} {{ nodeCount === 1 ? 'step' : 'steps' }}
        </div>
      </div>

      <div v-if="planData" class="mb-4">
        <PlanVisualization :plan="planData" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ClipboardDocumentListIcon } from '@heroicons/vue/24/outline'
import PlanVisualization from '../PlanVisualization.vue'

const props = defineProps({
  prompt: {
    type: String,
    required: true
  },
  planData: {
    type: Object,
    default: null
  },
  completed: {
    type: Boolean,
    default: false
  },
  approved: {
    type: Boolean,
    default: false
  },
  showPlan: {
    type: Boolean,
    default: true  // Default true for backward compat; set false when plan is shown separately
  }
})

const nodeCount = computed(() => props.planData?.nodes?.length || 0)
</script>
