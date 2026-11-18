<template>
  <div v-if="!onTile" class="my-1.5 flex items-center gap-2">
    <span class="text-[12px] text-content-secondary">{{ at.label || 'Your rating' }}</span>
    <div class="flex" @mouseleave="hover = 0">
      <button
        v-for="n in 5"
        :key="n"
        type="button"
        class="flex h-7 w-6 items-center justify-center coarse:h-11 coarse:w-9 disabled:cursor-default"
        :aria-label="`${n} of 5`"
        :disabled="sheet.readonly.value || !kid"
        @mouseenter="hover = n"
        @click="set(n)"
      >
        <StarIcon class="h-4 w-4 transition-colors" :class="(hover || value) >= n ? 'text-amber-400' : 'text-content-muted/40'" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
// <stimma-rating id label>: 1-5 on something that isn't one picture (a direction,
// a section). Tied to a picture with for=, it makes that picture's own rating stars.
import { computed, ref } from 'vue'
import { StarIcon } from '@heroicons/vue/24/solid'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const onTile = computed(() => sheet.isTile(props.at.for))
const hover = ref(0)
const value = computed(() => Number(props.kid ? sheet.answers.value[props.kid]?.value || 0 : 0))
function set(n: number) {
  if (props.kid) sheet.setAnswer(props.kid, value.value === n ? 0 : n)
}
</script>
