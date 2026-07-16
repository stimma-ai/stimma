<template>
  <span
    v-if="isStimma"
    class="flex h-10 w-10 shrink-0 items-center justify-center text-content-secondary"
    aria-hidden="true"
  >
    <span class="h-7 w-7 bg-current [mask-image:url('/logo.png')] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url('/logo.png')] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]"></span>
  </span>
  <span v-else-if="isComfy" class="flex h-10 w-10 shrink-0 items-center justify-center text-content-secondary" aria-hidden="true">
    <ComfyUIIcon class="h-8 w-8" />
  </span>
  <span v-else class="flex h-10 w-10 shrink-0 items-center justify-center text-content-muted" aria-hidden="true">
    <WrenchScrewdriverIcon class="h-7 w-7" />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { WrenchScrewdriverIcon } from '@heroicons/vue/24/outline'
import { isComfyUIProvider } from '../../utils/toolProviderBrands'
import ComfyUIIcon from './ComfyUIIcon.vue'

const props = defineProps<{
  provider?: { id?: string | null; name?: string | null; provider_name?: string | null } | null
  kind?: 'stimma' | 'comfyui' | 'custom'
}>()

const isStimma = computed(() => props.kind === 'stimma' || props.provider?.id === 'stimma-cloud')
const isComfy = computed(() => props.kind === 'comfyui' || isComfyUIProvider(props.provider))
</script>
