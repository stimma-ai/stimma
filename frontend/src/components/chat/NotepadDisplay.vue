<template>
  <div
    class="bg-surface/80 rounded-lg border border-edge-subtle overflow-hidden transition-all duration-200"
    :class="expanded ? 'min-w-[400px]' : ''"
  >
    <!-- Header -->
    <div
      class="flex items-center justify-between px-3.5 py-2 border-b border-amber-500/15 bg-amber-500/[0.06] cursor-pointer select-none"
      @click="expanded = !expanded"
    >
      <div class="flex items-center gap-2">
        <div class="p-1 rounded-md bg-amber-500/15 flex-shrink-0">
          <ClipboardDocumentListIcon class="w-3.5 h-3.5 text-amber-500" />
        </div>
        <span class="text-sm font-medium text-amber-400">Notepad</span>
        <ChevronRightIcon
          class="w-3.5 h-3.5 text-content-muted transition-transform duration-200 flex-shrink-0"
          :class="{ 'rotate-90': expanded }"
        />
      </div>
      <span v-if="tasks.length" class="text-xs text-content-muted tabular-nums">
        {{ doneCount }}/{{ tasks.length }}
      </span>
    </div>

    <!-- Body (collapsible) -->
    <div v-show="expanded" class="px-3.5 py-3 space-y-3 select-text">
      <!-- Tasks -->
      <div v-if="tasks.length">
        <div class="text-xs font-semibold text-content-secondary mb-1.5">Tasks</div>
        <div class="space-y-1">
          <div
            v-for="task in tasks"
            :key="task.id"
            class="flex items-start gap-2 text-sm"
          >
            <!-- Status icon -->
            <span class="flex-shrink-0 mt-0.5">
              <CheckCircleIcon v-if="task.status === 'done'" class="w-4 h-4 text-green-500" />
              <span v-else-if="task.status === 'in_progress'" class="flex h-4 w-4 items-center justify-center">
                <StatusDot bucket="running" pulse />
              </span>
              <ExclamationCircleIcon v-else-if="task.status === 'failed'" class="w-4 h-4 text-red-500" />
              <span v-else class="inline-flex h-4 w-4 items-center justify-center">
                <span class="rounded-full h-2 w-2 border border-edge"></span>
              </span>
            </span>
            <!-- Task text -->
            <span
              :class="[
                task.status === 'done' ? 'text-content-muted line-through' : 'text-content-secondary',
                task.status === 'failed' ? 'text-red-400' : ''
              ]"
            >{{ task.text }}</span>
          </div>
        </div>
      </div>

      <!-- Scratchpad -->
      <div v-if="scratchpad">
        <div class="text-xs font-semibold text-content-secondary mb-1.5">Scratchpad</div>
        <pre class="text-sm text-content-secondary whitespace-pre-wrap font-mono leading-relaxed">{{ scratchpad }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CheckCircleIcon, ExclamationCircleIcon } from '@heroicons/vue/20/solid'
import { ClipboardDocumentListIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import StatusDot from '../ui/StatusDot.vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  scratchpad: { type: String, default: '' },
})

const expanded = ref(true)

const doneCount = computed(() => props.tasks.filter(t => t.status === 'done').length)
</script>
