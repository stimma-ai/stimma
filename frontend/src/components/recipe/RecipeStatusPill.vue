<template>
  <span class="inline-flex items-center gap-1.5 min-w-0">
    <span
      class="w-1.5 h-1.5 rounded-full flex-shrink-0"
      :class="dotClass"
    ></span>
    <span class="truncate" :class="textClass">
      {{ statusText }}
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import { useRecipeStatus } from '../../composables/useRecipeStatus'
import { useRecipeCounts } from '../../composables/useRecipeCounts'

interface Props {
  recipeId: number | string | null | undefined
  showPending?: boolean
  textClass?: string
}

const props = withDefaults(defineProps<Props>(), {
  showPending: false,
  textClass: 'text-[11px] text-content-muted',
})

const recipeIdRef = toRef(props, 'recipeId')
const { label, dotClass } = useRecipeStatus(recipeIdRef)
const { countFor } = useRecipeCounts()
const pending = computed(() => countFor(props.recipeId))
const statusText = computed(() => {
  if (!props.showPending || pending.value <= 0 || label.value === 'Error') return label.value
  return `${label.value} · ${pending.value} pending`
})
</script>
