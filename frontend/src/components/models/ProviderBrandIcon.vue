<template>
  <ModelVendorIcon v-if="modelVendor" :model="modelVendor" :size="size" />
  <span
    v-else
    class="inline-flex shrink-0 items-center justify-center overflow-hidden text-content-secondary [&_svg]:block [&_svg]:h-full [&_svg]:w-full"
    :class="sizeClass"
    :title="label"
    :aria-label="label"
  >
    <CpuChipIcon v-if="props.provider === 'local'" aria-hidden="true" />
    <span v-else-if="providerSvg" class="contents" v-html="safeProviderSvg" />
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7" />
    </svg>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ModelVendorIcon from './ModelVendorIcon.vue'
import type { ModelVendorId } from '../../utils/modelVendors'
import { FIREWORKS_SVG, GOOGLE_GEMINI_SVG, OPENROUTER_SVG, TOGETHER_AI_SVG } from '../../utils/modelVendorSvgs'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { CpuChipIcon } from '@heroicons/vue/24/outline'

const props = withDefaults(defineProps<{
  provider: string | null | undefined
  size?: 'sm' | 'md' | 'lg'
}>(), { size: 'md' })

const modelVendor = computed<ModelVendorId | null>(() => {
  if (props.provider === 'openai' || props.provider === 'anthropic' || props.provider === 'xai') return props.provider
  return null
})
const providerSvg = computed(() => ({
  google: GOOGLE_GEMINI_SVG,
  together: TOGETHER_AI_SVG,
  fireworks: FIREWORKS_SVG,
  openrouter: OPENROUTER_SVG,
}[props.provider || ''] || ''))
const safeProviderSvg = computed(() => sanitizeSvg(providerSvg.value))
const label = computed(() => ({
  google: 'Google',
  together: 'Together AI',
  fireworks: 'Fireworks AI',
  openrouter: 'OpenRouter',
}[props.provider || ''] || 'Model provider'))
const sizeClass = computed(() => ({ sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-8 w-8' }[props.size]))
</script>
