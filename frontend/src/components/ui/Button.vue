<script setup lang="ts">
import { computed } from 'vue'
import Spinner from './Spinner.vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost' | 'link'
  size?: 'sm' | 'md'
  loading?: boolean
  disabled?: boolean
}>(), {
  variant: 'primary',
  size: 'md',
  loading: false,
  disabled: false,
})

const emit = defineEmits<{
  click: [MouseEvent]
}>()

function onClick(e: MouseEvent) {
  if (props.disabled || props.loading) return
  emit('click', e)
}

const isLink = computed(() => props.variant === 'link')

const variantClasses: Record<string, string> = {
  primary: 'bg-accent hover:bg-accent/90 text-white',
  secondary: 'bg-surface-raised hover:bg-surface-hover text-content',
  ghost: 'text-content-secondary hover:text-content hover:bg-overlay-subtle',
  danger: 'bg-red-600 hover:bg-red-500 text-white',
  'danger-ghost': 'text-red-400 hover:bg-red-500/10',
  link: 'text-accent underline hover:text-accent/90',
}

const sizeClasses: Record<string, string> = {
  sm: 'px-2.5 py-1.5 text-xs',
  md: 'px-3 py-2 text-sm',
}
</script>

<template>
  <button
    type="button"
    v-bind="$attrs"
    class="inline-flex items-center justify-center gap-1.5 font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:opacity-50 disabled:cursor-not-allowed"
    :class="[
      variantClasses[variant],
      !isLink && 'rounded-md',
      !isLink && sizeClasses[size],
      isLink && (size === 'sm' ? 'text-xs' : 'text-sm'),
    ]"
    :disabled="disabled || loading"
    @click="onClick"
  >
    <Spinner v-if="loading" :size="size === 'sm' ? 'sm' : 'md'" />
    <slot v-else name="icon" />
    <slot />
  </button>
</template>
