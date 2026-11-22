<template>
  <!-- Docks on top of the composer, like the message queue: work the agent
       started that is still running while the conversation goes on. Its line
       opens to show what the work has made so far. -->
  <div class="bg-field divide-y divide-edge-subtle">
    <div v-for="task in tasks" :key="task.id">
      <div class="flex items-center gap-1 min-h-10 py-1 pl-1.5 pr-1.5">
        <button
          type="button"
          class="flex flex-1 min-w-0 items-center gap-2.5 self-stretch rounded-md pl-1.5 pr-1 text-left hover:bg-overlay-faint focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :aria-expanded="open.has(task.id)"
          :title="open.has(task.id) ? 'Hide' : 'See what it has made so far'"
          @click="toggle(task.id)"
        >
          <Spinner size="sm" :value="line(task).fraction == null ? null : line(task).fraction! * 100" class="flex-shrink-0" />
          <span class="flex-1 min-w-0 text-sm truncate">
            <span class="text-content">{{ line(task).title }}</span>
            <span v-if="line(task).summary" class="text-content-muted"> · {{ line(task).summary }}</span>
          </span>
          <Caret :open="open.has(task.id)" class="text-content-tertiary" />
        </button>
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
      <BackgroundTaskPeek
        v-if="open.has(task.id) && chatId != null"
        :chat-id="chatId"
        :task-id="task.id"
        :version="version(task)"
        @view="id => emit('view', id)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import Spinner from '../ui/Spinner.vue'
import Caret from '../ui/Caret.vue'
import BackgroundTaskPeek from './BackgroundTaskPeek.vue'
import {
  backgroundTaskLine,
  type BackgroundTaskCounts,
  type BackgroundTaskProgress,
} from '../../utils/backgroundTaskLine'

export type { BackgroundTaskCounts, BackgroundTaskProgress }

export interface BackgroundTask {
  id: string
  label: string
  state: string
  counts: BackgroundTaskCounts
  items?: { kind?: string }[]
  progress?: BackgroundTaskProgress
  waiting_for?: string | null
}

defineProps<{ tasks: BackgroundTask[]; chatId?: number | null }>()
const emit = defineEmits<{ stop: [id: string]; view: [mediaId: number] }>()

const stopping = reactive(new Set<string>())
const open = reactive(new Set<string>())

const line = backgroundTaskLine

function version(task: BackgroundTask): string {
  return JSON.stringify(task.counts)
}

function toggle(id: string) {
  if (open.has(id)) open.delete(id)
  else open.add(id)
}

function stop(id: string) {
  stopping.add(id)
  emit('stop', id)
}
</script>
