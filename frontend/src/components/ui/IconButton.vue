<script setup lang="ts">
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  variant?: 'ghost' | 'danger'
  /** md = 28px (rows, panels); lg = 32px (headers and toolbars). 44px on coarse pointers. */
  size?: 'md' | 'lg'
  /** A toggle that is on (a panel is open, a mode is armed): neutral raised fill. */
  active?: boolean
  disabled?: boolean
}>(), {
  variant: 'ghost',
  size: 'md',
  active: false,
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
    class="inline-flex flex-none items-center justify-center rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:opacity-50 disabled:cursor-not-allowed coarse:h-11 coarse:w-11"
    :class="[size === 'lg' ? 'h-8 w-8' : 'h-7 w-7', active ? 'bg-overlay-light text-content' : variantClasses[variant]]"
    :disabled="disabled"
    :aria-pressed="active || undefined"
    @click="onClick"
  >
    <slot />
  </button>
</template>
