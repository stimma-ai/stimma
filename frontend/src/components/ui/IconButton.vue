<script setup lang="ts">
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  variant?: 'ghost' | 'danger'
  disabled?: boolean
}>(), {
  variant: 'ghost',
  disabled: false,
})

const emit = defineEmits<{
  click: [MouseEvent]
}>()

function onClick(e: MouseEvent) {
  emit('click', e)
}

const variantClasses: Record<string, string> = {
  ghost: 'text-content-secondary hover:text-content hover:bg-overlay-subtle',
  danger: 'text-red-400 hover:bg-red-500/10',
}
</script>

<template>
  <button
    type="button"
    v-bind="$attrs"
    class="inline-flex items-center justify-center w-7 h-7 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:opacity-50 disabled:cursor-not-allowed"
    :class="variantClasses[variant]"
    :disabled="disabled"
    @click="onClick"
  >
    <slot />
  </button>
</template>
