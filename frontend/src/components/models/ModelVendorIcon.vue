<template>
  <span
    class="inline-flex shrink-0 items-center justify-center overflow-hidden text-content-secondary [&_svg]:block [&_svg]:h-full [&_svg]:w-full"
    :class="sizeClass"
    :title="vendor?.label || 'Unknown model maker'"
    :aria-label="vendor?.label || 'Unknown model maker'"
  >
    <span v-if="vendor?.svg" class="contents" v-html="safeSvg" />
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 3.75h4.5m-4.5 16.5h4.5M4.5 9.75v4.5m15-4.5v4.5M7.5 6.75h9v10.5h-9V6.75Z" />
      <path stroke-linecap="round" stroke-linejoin="round" d="M10 10h4v4h-4z" />
    </svg>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { getModelVendorInfo, type ModelLike } from '../../utils/modelVendors'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = withDefaults(defineProps<{
  model: ModelLike | string | null | undefined
  size?: 'sm' | 'md' | 'lg'
}>(), { size: 'md' })

const vendor = computed(() => getModelVendorInfo(props.model))
const safeSvg = computed(() => sanitizeSvg(vendor.value?.svg || ''))
const sizeClass = computed(() => ({ sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-8 w-8' }[props.size]))
</script>
