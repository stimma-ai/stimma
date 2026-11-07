<template>
  <Tooltip :text="detail || providerName" class="shrink-0">
    <span role="img" :aria-label="providerName" class="flex h-5 w-5 items-center justify-center text-content-muted">
      <span v-if="cloud" class="h-4 w-4 bg-current [mask-image:url('/logo.svg')] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url('/logo.svg')] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]" />
      <ComfyUIIcon v-else-if="isComfy" class="h-4 w-4" />
      <img v-else-if="isDrawThings" src="/drawthings.png" alt="" class="h-4 w-4 rounded-md" draggable="false" />
      <span v-else class="flex h-5 w-5 items-center justify-center rounded-full bg-overlay-subtle text-[9px] font-medium leading-none">{{ initials }}</span>
    </span>
  </Tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Tooltip from '../ui/Tooltip.vue'
import ComfyUIIcon from './ComfyUIIcon.vue'
import { isComfyUIProvider } from '../../utils/toolProviderBrands'

const props = defineProps<{
  providerName: string
  providerId?: string
  cloud?: boolean
  detail?: string
}>()

const isComfy = computed(() => isComfyUIProvider({ id: props.providerId, name: props.providerName }))
const isDrawThings = computed(() => /^drawthings(?:-|$)/.test(props.providerId || ''))
const initials = computed(() => {
  const words = props.providerName.trim().split(/\s+/).filter(Boolean)
  return (words.length > 1 ? words.slice(0, 2).map(word => Array.from(word)[0]).join('') : Array.from(words[0] || '?').slice(0, 2).join('')).toLocaleUpperCase()
})
</script>
