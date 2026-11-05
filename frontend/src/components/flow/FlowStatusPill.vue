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
import { useFlowStatus } from '../../composables/useFlowStatus'
import { useFlowCounts } from '../../composables/useFlowCounts'
import { displayFlowStatus } from '../../utils/flowStatus'

interface Props {
  flowId: number | string | null | undefined
  showPending?: boolean
  textClass?: string
}

const props = withDefaults(defineProps<Props>(), {
  showPending: false,
  textClass: 'text-[11px] text-content-muted',
})

const flowIdRef = toRef(props, 'flowId')
const { label, dotClass } = useFlowStatus(flowIdRef)
const { countFor } = useFlowCounts()
const pending = computed(() => countFor(props.flowId))
const statusText = computed(() => {
  const text = displayFlowStatus(label.value)
  if (!props.showPending || pending.value <= 0 || label.value === 'Error' || label.value === 'Tool unavailable') return text
  return `${text} · ${pending.value} pending`
})
</script>
