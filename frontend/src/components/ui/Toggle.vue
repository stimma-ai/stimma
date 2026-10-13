<script setup lang="ts">
// Atelier Toggle (DESIGN.md §2 tier 2): the settings-row switch. Accent
// track when on, surface-hover when off, white knob. The hit area grows to
// 44px on coarse pointers (§1.11) without changing the drawn switch.
withDefaults(defineProps<{
  modelValue: boolean
  disabled?: boolean
  /** Accessible name when no visible <label> points at the switch. */
  label?: string
}>(), {
  disabled: false,
  label: undefined,
})

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="label"
    :disabled="disabled"
    class="group relative inline-flex shrink-0 items-center justify-center rounded-full focus-visible:outline-none coarse:min-h-11 coarse:min-w-11 disabled:cursor-not-allowed"
    @click="emit('update:modelValue', !modelValue)"
  >
    <span
      class="relative block h-5 w-9 rounded-full transition-colors duration-150 group-focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface group-disabled:opacity-50"
      :class="modelValue ? 'bg-accent' : 'bg-surface-hover'"
    >
      <span
        class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-150"
        :class="modelValue ? 'translate-x-4' : 'translate-x-0'"
      />
    </span>
  </button>
</template>
