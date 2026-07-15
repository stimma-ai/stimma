<template>
  <ModelVendorIcon v-if="modelVendor" :model="modelVendor" :size="size" />
  <span
    v-else
    class="inline-flex shrink-0 items-center justify-center overflow-hidden text-content-secondary [&_svg]:block [&_svg]:h-full [&_svg]:w-full"
    :class="sizeClass"
    :title="label"
    :aria-label="label"
  >
    <svg v-if="provider === 'openrouter'" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor">
      <title>OpenRouter</title>
      <path d="M16.778 1.844v1.919q-.569-.026-1.138-.032-.708-.008-1.415.037c-1.93.126-4.023.728-6.149 2.237-2.911 2.066-2.731 1.95-4.14 2.75-.396.223-1.342.574-2.185.798-.841.225-1.753.333-1.751.333v4.229s.768.108 1.61.333c.842.224 1.789.575 2.185.799 1.41.798 1.228.683 4.14 2.75 2.126 1.509 4.22 2.11 6.148 2.236.88.058 1.716.041 2.555.005v1.918l7.222-4.168-7.222-4.17v2.176c-.86.038-1.611.065-2.278.021-1.364-.09-2.417-.357-3.979-1.465-2.244-1.593-2.866-2.027-3.68-2.508.889-.518 1.449-.906 3.822-2.59 1.56-1.109 2.614-1.377 3.978-1.466.667-.044 1.418-.017 2.278.02v2.176L24 6.014Z" />
    </svg>
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7" />
    </svg>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ModelVendorIcon from './ModelVendorIcon.vue'
import type { ModelVendorId } from '../../utils/modelVendors'

const props = withDefaults(defineProps<{
  provider: string | null | undefined
  size?: 'sm' | 'md' | 'lg'
}>(), { size: 'md' })

const modelVendor = computed<ModelVendorId | null>(() => {
  if (props.provider === 'openai' || props.provider === 'anthropic' || props.provider === 'xai') return props.provider
  return null
})
const label = computed(() => props.provider === 'openrouter' ? 'OpenRouter' : 'Model provider')
const sizeClass = computed(() => ({ sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-8 w-8' }[props.size]))
</script>
