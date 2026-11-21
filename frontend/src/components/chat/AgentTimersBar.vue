<template>
  <!-- Docks on top of the composer: wake-ups the agent set for itself, so
       the user can see it will come back, and when, and end it. -->
  <div class="bg-field divide-y divide-edge-subtle">
    <div
      v-for="timer in timers"
      :key="timer.id"
      class="flex items-center gap-2.5 min-h-10 py-1.5 pl-3 pr-1.5"
    >
      <ClockIcon class="h-4 w-4 flex-shrink-0 text-content-tertiary" />
      <div class="flex-1 min-w-0 text-sm truncate" :title="timer.note">
        <span class="text-content">{{ when(timer) }}</span>
        <span v-if="timer.note" class="text-content-muted"> · {{ timer.note }}</span>
      </div>
      <button
        type="button"
        class="h-[26px] px-2.5 rounded-md border border-edge bg-surface-raised/50 text-xs text-content-secondary hover:bg-surface-raised hover:text-content transition-colors flex-shrink-0 disabled:opacity-50"
        :disabled="cancelling.has(timer.id)"
        @click="cancel(timer.id)"
      >
        {{ cancelling.has(timer.id) ? 'Cancelling' : 'Cancel' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ClockIcon } from '@heroicons/vue/24/outline'

export interface AgentTimer {
  id: string
  note: string
  repeats: boolean
  every_minutes?: number
  after_minutes?: number
  next_fires_at?: string
  fires_in?: string
  fire_at_utc?: string
  state: string
}

const props = defineProps<{ timers: AgentTimer[] }>()
const emit = defineEmits<{ cancel: [id: string] }>()

const cancelling = reactive(new Set<string>())
// The parent refetches after every cancel, so a timer still listed can be retried.
watch(() => props.timers, () => cancelling.clear())
// Countdowns move on their own between server updates.
const now = ref(Date.now())
const tick = setInterval(() => { now.value = Date.now() }, 15_000)
onBeforeUnmount(() => clearInterval(tick))

function firesIn(timer: AgentTimer): string {
  if (!timer.fire_at_utc) return timer.fires_in ?? ''
  const mins = Math.max(0, (Date.parse(timer.fire_at_utc) - now.value) / 60_000)
  return mins < 1 ? 'under a minute' : minutes(mins)
}

function minutes(n: number | undefined): string {
  if (!n) return ''
  if (n < 60) return `${Math.round(n)} min`
  const h = Math.floor(n / 60)
  const m = Math.round(n % 60)
  return m ? `${h} h ${m} min` : `${h} h`
}

function when(timer: AgentTimer): string {
  const left = firesIn(timer)
  if (timer.repeats) return `Checks back every ${minutes(timer.every_minutes)}${left ? ` · next in ${left}` : ''}`
  return left ? `Checks back in ${left}` : 'Checks back soon'
}

function cancel(id: string) {
  cancelling.add(id)
  emit('cancel', id)
}
</script>
