<template>
  <!-- Docks on top of the composer, like the message queue: work the agent
       started that is still running while the conversation goes on. -->
  <div class="rounded-t-lg bg-field divide-y divide-edge-subtle">
    <div
      v-for="task in tasks"
      :key="task.id"
      class="flex items-center gap-2.5 min-h-10 py-1.5 pl-3 pr-1.5"
    >
      <Spinner size="sm" class="flex-shrink-0" />
      <div class="flex-1 min-w-0 text-sm truncate">
        <span class="text-content">{{ title(task) }}</span>
        <span v-if="summary(task)" class="text-content-muted"> · {{ summary(task) }}</span>
      </div>
      <button
        type="button"
        class="h-[26px] px-2.5 rounded-md border border-edge bg-surface-raised/50 text-xs text-content-secondary hover:bg-surface-raised hover:text-content transition-colors flex-shrink-0 disabled:opacity-50"
        :disabled="stopping.has(task.id)"
        title="Stop what's left of this; finished results stay"
        @click="stop(task.id)"
      >
        {{ stopping.has(task.id) ? 'Stopping' : 'Stop' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import Spinner from '../ui/Spinner.vue'

export interface BackgroundTaskCounts {
  done: number
  failed: number
  cancelled: number
  generating: number
  queued: number
  preparing: number
  waiting: number
}

export interface BackgroundTask {
  id: string
  label: string
  state: string
  counts: BackgroundTaskCounts
  items?: { kind?: string }[]
}

const props = defineProps<{ tasks: BackgroundTask[] }>()
const emit = defineEmits<{ stop: [id: string] }>()

const stopping = reactive(new Set<string>())

// A task whose total has grown since we first saw it is open-ended (code that
// keeps generating): "36 of 37" and "Generating 37 items" would read as a
// fixed batch, so it gets counts without a total.
const firstTotals = new Map<string, number>()
const growing = reactive(new Set<string>())
watch(() => props.tasks, (tasks) => {
  for (const task of tasks) {
    const n = total(task)
    if (!n) continue
    const first = firstTotals.get(task.id)
    if (first === undefined) firstTotals.set(task.id, n)
    else if (n > first) growing.add(task.id)
  }
}, { immediate: true, deep: true })
function isGrowing(task: BackgroundTask): boolean {
  return growing.has(task.id)
}

function total(task: BackgroundTask): number {
  const c = task.counts
  if (!c) return 0
  return c.done + c.failed + c.cancelled + c.generating + c.queued + c.preparing + c.waiting
}

const NOUNS: Record<string, [string, string]> = {
  image: ['image', 'images'],
  video: ['video', 'videos'],
  audio: ['audio clip', 'audio clips'],
}

// The agent's own label wins; otherwise name the run from what it makes.
function title(task: BackgroundTask): string {
  if (task.label) return task.label
  const n = total(task)
  if (!n) return 'Working…'
  const kinds = new Set((task.items || []).map(i => i.kind))
  const nouns = kinds.size === 1 ? NOUNS[[...kinds][0] ?? ''] : undefined
  const [one, many] = nouns ?? ['item', 'items']
  if (isGrowing(task)) return `Generating ${many}`
  return `Generating ${n} ${n === 1 ? one : many}`
}

function summary(task: BackgroundTask): string {
  const c = task.counts
  const n = total(task)
  if (!n) return ''
  const parts = task.label && !isGrowing(task) ? [`${c.done} of ${n} done`] : [`${c.done} done`]
  if (c.generating) parts.push(`${c.generating} in progress`)
  const queued = c.queued + c.preparing + c.waiting
  if (queued) parts.push(`${queued} queued`)
  if (c.failed) parts.push(`${c.failed} failed`)
  return parts.join(' · ')
}

function stop(id: string) {
  stopping.add(id)
  emit('stop', id)
}
</script>
