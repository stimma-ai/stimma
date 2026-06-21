<template>
  <div
    v-if="errors.length > 0"
    class="flex flex-col bg-base border-t border-edge-subtle text-[12px]"
    :style="{ maxHeight: '50%', minHeight: '220px' }"
  >
    <div class="flex items-center gap-2 px-3 py-1 bg-surface border-b border-edge-subtle flex-shrink-0">
      <span class="w-1.5 h-1.5 rounded-full bg-red-500" />
      <span class="font-medium text-content-secondary">
        {{ errors.length }} {{ errors.length === 1 ? 'problem' : 'problems' }} in program.py
      </span>
      <span v-if="summaryText" class="text-content-muted text-[11px]">{{ summaryText }}</span>
    </div>

    <ul class="flex-1 min-h-0 overflow-auto">
      <li
        v-for="err in errors"
        :key="err.id"
        class="flex items-center gap-2 px-3 py-1 leading-tight cursor-pointer transition-colors border-b border-edge-subtle last:border-b-0"
        :class="rowClass(err)"
        :title="err.message"
        @click="emit('select', err.id)"
      >
        <span class="flex-shrink-0 w-3 h-3 inline-flex items-center justify-center text-red-500" aria-hidden="true">
          <svg viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3">
            <path d="M8 1.333A6.667 6.667 0 1 0 14.667 8 6.674 6.674 0 0 0 8 1.333Zm0 12A5.333 5.333 0 1 1 13.333 8 5.34 5.34 0 0 1 8 13.333ZM8.667 4v5h-1.334V4ZM8 11.333A.833.833 0 1 1 8.833 10.5.834.834 0 0 1 8 11.333Z" />
          </svg>
        </span>
        <span
          class="flex-shrink-0 px-1 py-px rounded text-[9px] font-mono uppercase tracking-wider"
          :class="badgeClass(err.source)"
        >{{ sourceLabel(err.source) }}</span>
        <span class="flex-1 min-w-0 truncate text-content-secondary">{{ err.summary || err.message }}</span>
        <span
          v-if="err.equationDisplayName || err.equationKey"
          class="flex-shrink-0 text-content-muted text-[11px] font-mono truncate max-w-[40%]"
          :title="err.equationKey || ''"
        >
          {{ err.equationDisplayName || err.equationKey }}
        </span>
        <span
          class="flex-shrink-0 font-mono text-[11px]"
          :class="err.line ? 'text-blue-400' : 'text-content-muted'"
        >
          program.py<template v-if="err.line">:{{ err.line }}</template>
        </span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CodeError, CodeErrorSource } from '../../composables/useFlowCodeErrors'

const props = defineProps<{
  errors: CodeError[]
  selectedId?: string | null
}>()
const emit = defineEmits<{
  // Toggle: parent treats a repeat select on the same id as a deselect.
  (e: 'select', id: string): void
}>()

const summaryText = computed(() => {
  const counts: Record<CodeErrorSource, number> = { build: 0, 'dry-run': 0, runtime: 0 }
  for (const err of props.errors) counts[err.source]++
  const parts: string[] = []
  if (counts.build) parts.push(`${counts.build} build`)
  if (counts['dry-run']) parts.push(`${counts['dry-run']} dry-run`)
  if (counts.runtime) parts.push(`${counts.runtime} runtime`)
  return parts.join(' · ')
})

function sourceLabel(source: CodeErrorSource): string {
  if (source === 'dry-run') return 'DRY'
  if (source === 'runtime') return 'RUN'
  return 'BUILD'
}

function badgeClass(source: CodeErrorSource): string {
  if (source === 'build') return 'bg-orange-500/15 text-orange-400'
  if (source === 'dry-run') return 'bg-amber-500/15 text-amber-400'
  return 'bg-red-500/15 text-red-400'
}

function rowClass(err: CodeError): string {
  return err.id === props.selectedId
    ? 'bg-blue-500/15 hover:bg-blue-500/20'
    : 'hover:bg-overlay-subtle'
}
</script>
