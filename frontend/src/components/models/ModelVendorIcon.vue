<template>
  <span
    v-if="vendor"
    class="inline-flex shrink-0 items-center justify-center overflow-hidden text-content-secondary [&_svg]:block [&_svg]:h-full [&_svg]:w-full"
    :class="sizeClass"
    :title="vendor.label"
    :aria-label="vendor.label"
    v-html="safeSvg"
  />
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
