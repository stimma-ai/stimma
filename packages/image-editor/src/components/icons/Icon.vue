<script setup lang="ts">
import { computed } from 'vue';
import { icons, type IconName } from './index';

const props = withDefaults(
  defineProps<{
    name: IconName;
    size?: number | string;
  }>(),
  {
    size: 20,
  }
);

const svgContent = computed(() => icons[props.name]);

const style = computed(() => ({
  width: typeof props.size === 'number' ? `${props.size}px` : props.size,
  height: typeof props.size === 'number' ? `${props.size}px` : props.size,
}));
</script>

<template>
  <span
    class="stimma-icon"
    :style="style"
    v-html="svgContent"
  />
</template>

<style scoped>
.stimma-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.stimma-icon :deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
