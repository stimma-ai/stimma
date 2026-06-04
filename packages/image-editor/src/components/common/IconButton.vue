<script setup lang="ts">
defineProps<{
  label: string;
  disabled?: boolean;
  active?: boolean;
}>();

defineEmits<{
  (e: 'click'): void;
}>();
</script>

<template>
  <button
    class="stimma-toolbar__button"
    :class="{ 'stimma-toolbar__button--active': active }"
    :disabled="disabled"
    :aria-label="label"
    :title="label"
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>
