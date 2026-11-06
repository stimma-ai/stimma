<script setup lang="ts">
// "New outputs": what happens automatically to everything this tool makes.
// Auto-markers and auto-delete sit together, always visible, under a label that
// says their scope. The heart and bookmark under the result act on that one
// result; these act on every run from here on.
import { computed } from 'vue'
import { TrashIcon } from '@heroicons/vue/24/outline'
import AutoMarkPicker from './AutoMarkPicker.vue'
import AutoDeletePicker from '../AutoDeletePicker.vue'

interface Marker { id: number; name: string; icon_svg: string; color: string }

const props = defineProps<{
  markers: Marker[]
  autoMarkerIds: number[]
  autoDelete: string
  /** Compact layouts: auto-delete's long list of durations lives in the run
   *  sheet, so its button opens that sheet. */
  sheet?: boolean
}>()
const emit = defineEmits<{
  'update:autoMarkerIds': [value: number[]]
  'update:autoDelete': [value: string]
  configure: []
}>()

const deleteArmed = computed(() => props.autoDelete !== 'never')
</script>

<template>
  <div role="group" aria-label="New outputs" class="mb-3 flex min-h-8 items-center gap-2 coarse:mb-1 coarse:min-h-11">
    <span class="text-ctl font-semibold text-content-secondary">New outputs</span>
    <div class="-mr-2 ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">
      <AutoMarkPicker
        :markers="markers"
        :model-value="autoMarkerIds"
        @update:model-value="emit('update:autoMarkerIds', $event)"
      />
      <button
        v-if="sheet"
        type="button"
        class="flex h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors"
        :class="deleteArmed ? 'text-accent-hi' : 'text-content-secondary'"
        :aria-label="deleteArmed ? `Auto-delete after ${autoDelete}` : 'Auto-delete off'"
        @click="emit('configure')"
      >
        <TrashIcon class="h-icon-nav w-icon-nav" aria-hidden="true" />
        <span v-if="deleteArmed" class="font-mono tabular-nums">{{ autoDelete }}</span>
      </button>
      <AutoDeletePicker
        v-else
        size="small"
        :model-value="autoDelete"
        @update:model-value="emit('update:autoDelete', $event)"
      />
    </div>
  </div>
</template>
