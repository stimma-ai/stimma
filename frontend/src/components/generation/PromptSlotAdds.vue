<template>
  <!-- Things the prompt doesn't mention that could vary: one click writes one in as a slot. -->
  <div v-if="adds.length" class="px-3 pt-1 pb-1.5 flex flex-wrap items-center gap-1.5" data-slot-adds>
    <button
      v-for="a in adds"
      :key="a.name"
      type="button"
      :disabled="!!adding"
      :aria-busy="adding === a.name || undefined"
      class="inline-flex items-center gap-1 pl-1.5 pr-2.5 py-1 coarse:py-1.5 rounded-full text-xs text-content-muted hover:text-content hover:bg-surface-hover disabled:pointer-events-none outline-none focus-visible:ring-1 focus-visible:ring-selection/60 transition-colors"
      :data-slot-add="a.name"
      @mousedown.prevent
      @click="emit('add', a.name)"
    ><Spinner v-if="adding === a.name" size="sm" /><PlusIcon v-else class="w-3 h-3" />{{ a.label }}</button>
  </div>
</template>

<script setup lang="ts">
import { PlusIcon } from '@heroicons/vue/24/outline'
import Spinner from '../ui/Spinner.vue'
import type { SuggestedAdd } from '../../composables/usePromptSuggestions'

defineProps<{ adds: SuggestedAdd[]; adding: string | null }>()
const emit = defineEmits<{ (e: 'add', name: string): void }>()
</script>
